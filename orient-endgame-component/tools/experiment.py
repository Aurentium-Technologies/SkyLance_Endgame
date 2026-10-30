"""Shared validation, PGN parsing, and rating mathematics for Orient experiments.

The rating is a local logistic score estimate anchored to an external list. It is
neither a FIDE rating nor an independently assigned CCRL rating.
"""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import subprocess
import sys
import threading


class ExperimentError(ValueError):
    pass


_LEASE_FDS = set()
_LEASE_FDS_LOCK = threading.Lock()


def compute_child_fds():
    """Descriptors designated heavy children retain across exec, including from worker threads."""
    with _LEASE_FDS_LOCK:
        return tuple(sorted(_LEASE_FDS))


@contextmanager
def compute_lease(owner, lock_path=None):
    """One heavy local experiment controller; kernel lock survives chat turns.

    Its controller may run up to three matches, or four training threads. Locks
    remain held by any designated inheriting child after controller exit.
    Metadata is informational; the kernel file lock is authoritative.
    Tests may supply a temporary lock_path; real controllers use the shared default.
    """
    import fcntl
    path = (Path(lock_path) if lock_path is not None else
            Path(__file__).resolve().parents[1] / "artifacts" / "compute.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.seek(0)
            raise ExperimentError("Another local experiment owns compute: " + lock.read().strip()) from None
        lock.seek(0)
        lock.truncate()
        json.dump({"owner": owner, "started_utc": utc_now()}, lock)
        lock.flush()
        descriptor = lock.fileno()
        with _LEASE_FDS_LOCK:
            _LEASE_FDS.add(descriptor)
        try:
            yield descriptor
        finally:
            with _LEASE_FDS_LOCK:
                _LEASE_FDS.discard(descriptor)
            # Closing this handle releases only our ownership. Explicit LOCK_UN
            # would also unlock the shared file description inherited by children.


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ExperimentError(f"Refusing to overwrite {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def artifact(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ExperimentError(f"Not a regular file: {path}")
    return {"path": str(path), "sha256": sha256(path)}


def verify_artifact(record):
    if not isinstance(record, dict) or not {"path", "sha256"} <= record.keys():
        raise ExperimentError("Missing artifact path or SHA-256")
    if not Path(record["path"]).is_file():
        raise ExperimentError(f"Missing artifact: {record['path']}")
    if sha256(record["path"]) != record["sha256"]:
        raise ExperimentError(f"SHA-256 mismatch: {record['path']}")


def metadata():
    result = {"timestamp_utc": utc_now(), "platform": platform.platform(),
              "machine": platform.machine(), "python": sys.version,
              "logical_cpus": os.cpu_count()}
    for name, cmd in (("cpu", ["lscpu"]), ("git_commit", ["git", "rev-parse", "HEAD"]),
                      ("git_status", ["git", "status", "--porcelain"])):
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
            result[name] = run.stdout.strip() if run.returncode == 0 else "unavailable"
        except (OSError, subprocess.TimeoutExpired):
            result[name] = "unavailable"
    return result


def fen_key(fen):
    fields = fen.strip().split()
    if len(fields) != 6:
        raise ExperimentError(f"Expected six FEN fields: {fen!r}")
    return " ".join(fields[:4])


def read_epd(path):
    positions = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 4:
            raise ExperimentError("Malformed opening EPD")
        # Our generated EPD uses four FEN fields followed by an id operation.
        positions.append(" ".join(fields[:4]) + " 0 1")
    keys = [fen_key(fen) for fen in positions]
    if len(keys) != len(set(keys)):
        raise ExperimentError("Duplicate opening positions")
    return positions


def epd_text(positions, prefix):
    return "".join(f'{fen_key(fen)} id "{prefix}-{i:05d}";\n'
                   for i, fen in enumerate(positions))


def require_number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ExperimentError(f"{label} must be a finite number")
    if not low <= value <= high:
        raise ExperimentError(f"{label} must be in [{low}, {high}]")


def verify_corpora(record):
    """Verify the frozen research books and their disjoint position groups."""
    verify_artifact(record)
    corpus = read_json(record["path"])
    if corpus.get("schema_version") != 1:
        raise ExperimentError("Unsupported research corpus schema")
    groups = []
    for name in ("development", "confirmation", "holdout"):
        item = corpus.get("corpora", {}).get(name, {})
        verify_artifact(item)
        keys = {fen_key(fen) for fen in read_epd(item["path"])}
        if not keys or type(item.get("positions")) is not int or item["positions"] != len(keys):
            raise ExperimentError("Research corpus position accounting mismatch: " + name)
        if any(keys & other for other in groups):
            raise ExperimentError("Research opening corpora overlap")
        groups.append(keys)
    return corpus


def verify_original_network(candidate, expected_corpora=None):
    enabled = candidate.get("options", {}).get("Use NNUE", False)
    if type(enabled) is not bool:
        raise ExperimentError("Candidate Use NNUE must be a JSON boolean")
    if not enabled:
        return
    verify_artifact(candidate.get("network_manifest", {}))
    trained = read_json(candidate["network_manifest"]["path"])
    if trained.get("kind") != "orient-own-network-v1" or trained.get("initialization") != "random; no imported weights or resume":
        raise ExperimentError("Candidate network must originate from Orient's original random-initialized trainer")
    for field in ("trainer", "own_state", "integer_reference", "corpus_manifest"):
        verify_artifact(trained.get(field, {}))
    if 'support' in trained:
        verify_artifact(trained['support'])
    corpus = verify_corpora(trained["corpus_manifest"])
    if expected_corpora is None:
        expected_corpora = trained["corpus_manifest"]
    verify_artifact(expected_corpora)
    if trained["corpus_manifest"]["sha256"] != expected_corpora["sha256"]:
        raise ExperimentError("Network or ancestor used a different frozen research corpus")
    excluded = trained.get("excluded_corpora", [])
    if not isinstance(excluded, list):
        raise ExperimentError("Original network has no recorded corpus exclusions")
    for item in excluded:
        verify_artifact(item)
    excluded_hashes = {item["sha256"] for item in excluded}
    if any(corpus["corpora"][name]["sha256"] not in excluded_hashes
           for name in ("development", "confirmation", "holdout")):
        raise ExperimentError("Original network did not exclude all three research corpora")
    command = trained.get("command")
    if (not isinstance(command, list) or len(command) < 2
            or any(not isinstance(arg, str) or not arg for arg in command)
            or not isinstance(trained.get("working_directory"), str)):
        raise ExperimentError("Original training invocation was not recorded")
    for field, low, high in (("requested_epochs", 1, 100), ("batch_size", 16, 8192), ("threads", 1, 4)):
        if type(trained.get(field)) is not int or not low <= trained[field] <= high:
            raise ExperimentError("Missing or invalid training setting: " + field)
    require_number(trained.get("learning_rate"), "training learning rate", 0, 0.1)
    if trained["learning_rate"] == 0:
        raise ExperimentError("Training learning rate must be positive")
    optimizer = trained.get("optimizer", {})
    if (not isinstance(optimizer, dict) or optimizer.get("name") != "torch.optim.AdamW"
            or optimizer.get("learning_rate") != trained["learning_rate"]
            or not {"betas", "eps", "weight_decay", "amsgrad", "maximize", "foreach",
                    "capturable", "differentiable", "fused"} <= optimizer.keys()):
        raise ExperimentError("Original optimizer configuration was not recorded")
    verify_artifact(candidate.get("network", {}))
    verify_artifact(trained.get("network", {}))
    if candidate["network"] != trained["network"]:
        raise ExperimentError("Frozen network differs from original training export")
    verify_artifact(trained.get("export_verification", {}))
    exported = read_json(trained["export_verification"]["path"])
    if (exported.get("kind") != "orient-integer-export-verification-v1" or exported.get("passed") is not True
            or type(exported.get("positions_checked")) is not int or exported["positions_checked"] < 20
            or len(exported.get("positions", [])) != exported["positions_checked"]
            or exported.get("network") != trained["network"]):
        raise ExperimentError("Original network export lacks Python/C++ integer agreement evidence")
    verify_artifact(exported.get("engine", {}))
    verify_artifact(exported.get("reference", {}))
    if exported["reference"] != trained["integer_reference"]:
        raise ExperimentError("Integer agreement used a different frozen reference")
    supplied = candidate.get("options", {}).get("EvalFile")
    if not isinstance(supplied, str) or Path(supplied).resolve() != Path(candidate["network"]["path"]).resolve():
        raise ExperimentError("EvalFile must identify the exact frozen original network")
    datasets = trained.get("datasets", [])
    if not datasets:
        raise ExperimentError("Original network has no self-play data provenance")
    for item in datasets:
        verify_artifact(item)
        data = read_json(item["path"])
        if data.get("kind") != "orient-own-selfplay-v1":
            raise ExperimentError("External engine labels cannot certify an original network")
        for key in ("dataset", "binary", "source_archive", "checkpoint"):
            verify_artifact(data.get(key, {}))
        source = read_json(data["checkpoint"]["path"])
        if source.get("additional_binaries", {}).get("orient-selfplay", {}).get("sha256") != data["binary"]["sha256"]:
            raise ExperimentError("Network labeler differs from its original source checkpoint")
        if source.get("source_archive", {}).get("sha256") != data["source_archive"]["sha256"]:
            raise ExperimentError("Network labeler source archive differs from its checkpoint")
        verify_original_network(data.get("evaluator", {"options": {"Use NNUE": False}}), expected_corpora)


def validate_manifest(manifest, verify=True):
    if manifest.get("schema_version") != 1:
        raise ExperimentError("Unsupported manifest schema_version")
    opponents = manifest.get("opponents", [])
    if verify:
        corpus_record = manifest.get("corpora", {})
        corpus = verify_corpora(corpus_record)
        verify_artifact(manifest.get("holdout", {}))
        if manifest["holdout"]["sha256"] != corpus["corpora"]["holdout"]["sha256"]:
            raise ExperimentError("Frozen holdout differs from the research corpus manifest")
        verify_original_network(manifest.get("candidate", {}), corpus_record)
    if len(opponents) != 6:
        raise ExperimentError("Certification requires exactly six opponents")
    names, families, ratings = set(), set(), []
    for engine in [manifest.get("candidate", {})] + opponents:
        if not isinstance(engine.get("name"), str) or not engine["name"].strip():
            raise ExperimentError("Every engine needs a name")
        if engine["name"] in names:
            raise ExperimentError("Duplicate engine name")
        names.add(engine["name"])
        if verify:
            verify_artifact(engine)
            for extra in engine.get("runtime_artifacts", []):
                verify_artifact(extra)
        opts = engine.get("options", {})
        if type(opts.get("Threads")) is not int or opts["Threads"] != 1 or type(opts.get("Hash")) is not int or opts["Hash"] != 256 or opts.get("Ponder") is not False:
            raise ExperimentError("Certification uses Threads=1, Hash=256 MiB, Ponder=false")
        if opts.get("UCI_LimitStrength") is True:
            raise ExperimentError("Strength-limited engines are ineligible")
    for engine in opponents:
        for field in ("family", "version", "source_url", "release_url", "license", "rating_source_url"):
            if not isinstance(engine.get(field), str) or not engine[field].strip():
                raise ExperimentError(f"Opponent requires {field}")
        if engine["family"].casefold() in families:
            raise ExperimentError("Use six independent engine families")
        families.add(engine["family"].casefold())
        require_number(engine.get("rating"), "rating", 100, 5000)
        require_number(engine.get("rating_error_95"), "rating_error_95", 0.01, 500)
        require_number(engine.get("rating_games"), "rating_games", 500, 100000000)
        ratings.append(engine["rating"])
    if sum(r < 3000 for r in ratings) != 3 or sum(r > 3000 for r in ratings) != 3:
        raise ExperimentError("Select three opponents below and three above 3000")
    protocol = manifest.get("protocol", {})
    if protocol != {"games_per_opponent": 1000, "total_games": 6000,
                    "time_control": "120+1", "concurrency": 3,
                    "max_moves": 500, "rating_target": 3000}:
        raise ExperimentError("Unexpected certification protocol")
    for field in ("fastchess", "holdout", "rating_snapshot"):
        if verify:
            verify_artifact(manifest.get(field, {}))
    if verify and len(read_epd(manifest["holdout"]["path"])) != 3000:
        raise ExperimentError("Certification holdout must have exactly 3000 unique positions")
    if verify:
        # The independent list is the authority for anchors; a hand-written
        # opponent spec cannot silently invent ratings or omit multi-CPU tags.
        from select_opponents import parse_snapshot
        rows = parse_snapshot(manifest["rating_snapshot"]["path"])
        listed = {r["name"]: r for r in rows}
        for engine in opponents:
            row = listed.get(engine.get("rating_name", engine["name"]))
            if row is None or not row["single_cpu"] or not row["snapshot_open_source_label"]:
                raise ExperimentError("Opponent is absent from eligible single-CPU snapshot rows")
            for field in ("rating", "rating_games", "rating_error_95"):
                if engine[field] != row[field]:
                    raise ExperimentError(f"Opponent {field} differs from saved CCRL snapshot")
        checkpoint_artifact = manifest["candidate"].get("checkpoint", {})
        verify_artifact(checkpoint_artifact)
        checkpoint = read_json(checkpoint_artifact["path"])
        verify_artifact(checkpoint.get("binary", {}))
        verify_artifact(checkpoint.get("source_archive", {}))
        if checkpoint["binary"]["sha256"] != manifest["candidate"]["sha256"]:
            raise ExperimentError("Candidate differs from frozen source/build checkpoint")
        verify_artifact(manifest.get("selection", {}))
        selection = read_json(manifest["selection"]["path"])
        verify_artifact(selection.get("snapshot", {}))
        verify_artifact(selection.get("catalogue", {}))
        if selection["snapshot"]["sha256"] != manifest["rating_snapshot"]["sha256"]:
            raise ExperimentError("Selection used a different rating snapshot")
        from select_opponents import select
        selected = select(rows, read_json(selection["catalogue"]["path"]))
        if selection.get("selected") != selected:
            raise ExperimentError("Selected opponents do not reproduce from reviewed release catalogue")
        by_name = {e["name"]: e for e in selected}
        for engine in opponents:
            selected_engine = by_name.get(engine.get("rating_name", engine["name"]))
            if selected_engine is None:
                raise ExperimentError("Manifest opponent differs from frozen nearest-release selection")
            for field in ("family", "version", "source_url", "release_url", "license"):
                if engine[field] != selected_engine[field]:
                    raise ExperimentError(f"Opponent {field} differs from reviewed release selection")
            # A release name/URL alone cannot bind an Elo anchor to the bytes
            # being run. Verify the selected author's executable and its saved
            # licence/probe evidence, then bind the campaign to that exact SHA.
            for field in ("binary", "license_artifact", "uci_probe"):
                verify_artifact(selected_engine.get(field, {}))
            selected_binary = selected_engine["binary"]
            if engine["sha256"] != selected_binary["sha256"]:
                raise ExperimentError("Opponent binary differs from selected author release")
            if "license_artifact" in engine:
                verify_artifact(engine["license_artifact"])
                if engine["license_artifact"]["sha256"] != selected_engine["license_artifact"]["sha256"]:
                    raise ExperimentError("Opponent licence differs from selected author release")
            probe = read_json(selected_engine["uci_probe"]["path"])
            verify_artifact(probe.get("binary", {}))
            if probe["binary"]["sha256"] != selected_binary["sha256"]:
                raise ExperimentError("Selected opponent UCI probe belongs to a different binary")
            if probe.get("exit_code") != 0 or "uciok" not in probe.get("stdout", "").splitlines():
                raise ExperimentError("Selected opponent has no successful saved UCI probe")
            advertised = re.findall(r"(?m)^option name (.*?) type ", probe["stdout"])
            if probe.get("supported_options") != advertised:
                raise ExperimentError("Selected opponent UCI option evidence is inconsistent")
            if engine.get("supported_options", advertised) != advertised:
                raise ExperimentError("Opponent UCI options differ from selected author binary probe")
            hash_range = re.search(r"(?m)^option name Hash type spin default [0-9]+ min ([0-9]+) max ([0-9]+)\s*$", probe["stdout"])
            if not hash_range or not int(hash_range[1]) <= 256 <= int(hash_range[2]):
                raise ExperimentError("Selected opponent cannot advertise the fixed 256 MiB Hash setting")


_TAG = re.compile(r'^\[([A-Za-z0-9_]+)\s+"((?:\\.|[^"\\])*)"\]\s*$')
_BAD_ENDING = re.compile(r"illegal|forfeit|crash|disconnect|stall|time.?out|time.?loss|loses on time|time limit|unterminated|abandon", re.I)


def parse_pgn(path):
    """Parse game headers and verify each complete movetext result.

    This deliberately is not a chess move parser; the independent tournament
    runner adjudicates legal play. Header/result consistency is checked here.
    """
    games, headers, body = [], {}, []

    def finish():
        nonlocal headers, body
        if not headers and not body:
            return
        result = headers.get("Result")
        if result not in ("1-0", "0-1", "1/2-1/2"):
            raise ExperimentError("Incomplete or invalid PGN Result")
        clean = re.sub(r"\{[^}]*\}|;[^\n]*", " ", "\n".join(body), flags=re.S)
        if not clean.split() or clean.split()[-1] != result:
            raise ExperimentError("PGN movetext result does not match Result tag")
        record = dict(headers)
        record["_movetext"] = clean
        games.append(record)
        headers, body = {}, []

    for line in Path(path).read_text(encoding="utf-8").splitlines():
        tag = _TAG.match(line.strip())
        if tag:
            if body:
                finish()
            key, value = tag.groups()
            if key in headers:
                raise ExperimentError(f"Duplicate PGN tag {key}")
            headers[key] = re.sub(r'\\(["\\])', r'\1', value)
        elif line.strip():
            body.append(line)
    finish()
    return games


def collect_pairs(games, candidate, opponent, expected_positions=None):
    pairs, failures = {}, []
    allowed = None if expected_positions is None else {fen_key(fen) for fen in expected_positions}
    points = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}
    wdl = [0, 0, 0]
    for game in games:
        white, black = game.get("White"), game.get("Black")
        if {white, black} != {candidate, opponent}:
            raise ExperimentError("Unexpected engine identity in PGN")
        if "FEN" not in game:
            raise ExperimentError("Certification PGNs must record their opening FEN")
        key = fen_key(game["FEN"])
        if allowed is not None and key not in allowed:
            raise ExperimentError("PGN opening absent from its frozen holdout slice")
        colour = "white" if white == candidate else "black"
        if colour in pairs.setdefault(key, {}):
            raise ExperimentError("Duplicate game/colour for opening pair")
        score = points[game["Result"]]
        if colour == "black":
            score = 1.0 - score
        pairs[key][colour] = score
        wdl[0 if score == 1 else 1 if score == 0.5 else 2] += 1
        ending = " ".join(game.get(t, "") for t in ("Termination", "ResultDetails", "TerminationDetails"))
        if _BAD_ENDING.search(ending):
            failures.append(ending)
        if re.search(r"\b500\.(?:\s|\.)", game.get("_movetext", "")) or int(game.get("PlyCount", "0")) >= 1000:
            failures.append("500-move safety cap reached")
    if any(set(pair) != {"white", "black"} for pair in pairs.values()):
        raise ExperimentError("Opening pair is missing a colour-reversed game")
    if allowed is not None and set(pairs) != allowed:
        raise ExperimentError("Missing opening pairs from frozen holdout")
    return [pair["white"] + pair["black"] for pair in pairs.values()], wdl, failures


def logistic_score(rating, anchor):
    exponent = max(-300, min(300, (anchor - rating) / 400.0))
    return 1.0 / (1.0 + 10.0 ** exponent)


def estimate_rating(scores, games, anchors):
    if not (len(scores) == len(games) == len(anchors)) or not scores:
        raise ExperimentError("Rating arrays must have equal nonzero length")
    for score, count, anchor in zip(scores, games, anchors):
        require_number(count, "game count", 1, 1000000000)
        require_number(score, "score", 0, count)
        require_number(anchor, "anchor", 100, 5000)
    if sum(games) <= 0 or sum(scores) <= 0 or sum(scores) >= sum(games):
        raise ExperimentError("A finite rating needs both scored and unscored points")
    lo, hi = min(anchors) - 5000, max(anchors) + 5000
    for _ in range(70):
        middle = (lo + hi) / 2
        expected = sum(n * logistic_score(middle, r) for n, r in zip(games, anchors))
        if expected < sum(scores):
            lo = middle
        else:
            hi = middle
    return (lo + hi) / 2


def percentile(values, probability):
    ordered = sorted(values)
    i = probability * (len(ordered) - 1)
    left = int(i)
    if ordered[left] == ordered[min(left + 1, len(ordered) - 1)]:
        return ordered[left]
    if not math.isfinite(ordered[left]) or not math.isfinite(ordered[min(left + 1, len(ordered) - 1)]):
        return ordered[left] if probability < .5 else ordered[min(left + 1, len(ordered) - 1)]
    return ordered[left] + (ordered[min(left + 1, len(ordered) - 1)] - ordered[left]) * (i - left)


def rating_analysis(pair_scores, anchors, errors, replicates=10000, seed=20261023):
    if len(pair_scores) != len(anchors) or len(anchors) != len(errors) or not anchors:
        raise ExperimentError("Mismatched rating inputs")
    if any(not row for row in pair_scores):
        raise ExperimentError("Every opponent needs game pairs")
    for row in pair_scores:
        for score in row:
            require_number(score, "pair score", 0, 2)
    for error in errors:
        require_number(error, "anchor uncertainty", 0, 500)
    if replicates < 100:
        raise ExperimentError("Use at least 100 bootstrap replicates")
    counts = [2 * len(row) for row in pair_scores]
    totals = [sum(row) for row in pair_scores]
    point = estimate_rating(totals, counts, anchors)
    rng = random.Random(seed)
    conditional, propagated = [], []
    for _ in range(replicates):
        sample = [sum(rng.choices(row, k=len(row))) for row in pair_scores]
        sampled_anchors = [rng.gauss(r, e / 1.959963984540054) for r, e in zip(anchors, errors)]
        # Rare saturated resamples are represented by unbounded endpoints.
        if sum(sample) == 0:
            conditional.append(float("-inf")); propagated.append(float("-inf"))
        elif sum(sample) == sum(counts):
            conditional.append(float("inf")); propagated.append(float("inf"))
        else:
            conditional.append(estimate_rating(sample, counts, anchors))
            propagated.append(estimate_rating(sample, counts, sampled_anchors))
    leave_one_out = []
    if len(anchors) > 1:
        for i in range(len(anchors)):
            subset_scores = totals[:i] + totals[i + 1:]
            subset_counts = counts[:i] + counts[i + 1:]
            if sum(subset_scores) == 0:
                leave_one_out.append(float("-inf"))
            elif sum(subset_scores) == sum(subset_counts):
                leave_one_out.append(float("inf"))
            else:
                leave_one_out.append(estimate_rating(subset_scores, subset_counts,
                                                     anchors[:i] + anchors[i + 1:]))
    return {"estimate": point,
            "conditional_interval_95": [percentile(conditional, .025), percentile(conditional, .975)],
            "anchor_propagated_interval_95": [percentile(propagated, .025), percentile(propagated, .975)],
            "leave_one_opponent_out": leave_one_out,
            "bootstrap_replicates": replicates, "bootstrap_seed": seed,
            "method": "logistic expected-score fit; opponent-stratified opening-pair bootstrap",
            "anchor_model": "independent Gaussian errors, sigma=published 95% half-width/1.959964; covariance unavailable",
            "limitations": "Local CCRL-anchored estimate; intervals do not cover hardware/pool transfer or unknown correlated anchor errors."}


def cli_main(function):
    try:
        function()
    except (ExperimentError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
