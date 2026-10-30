#!/usr/bin/env python3
"""Paired 015/root/compact-cache experiment; validation data, never training labels."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone

from experiment import compute_child_fds, compute_lease
from tablebase_manifest import verify_tablebase_manifest


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def geomean(values):
    values = list(values)
    if not values or any(value <= 0 or not math.isfinite(value) for value in values):
        raise ValueError("geometric means require finite positive measurements")
    return math.exp(sum(map(math.log, values)) / len(values))


def comparison(trials, candidate, baseline):
    """Ratios pair measurements, rather than dividing unpaired aggregate times."""
    ratios = {name: [] for name in ("search_speedup", "search_time_ratio", "root_speedup",
                                   "root_time_ratio", "root_p95_ratio", "distinct_time_ratio")}
    for pair in range(1, 6):
        left = next(row for row in trials if row["pair"] == pair and row["case"] == candidate)
        right = next(row for row in trials if row["pair"] == pair and row["case"] == baseline)
        ratios["search_speedup"].append(right["search_ms"] / left["search_ms"])
        ratios["search_time_ratio"].append(left["search_ms"] / right["search_ms"])
        ratios["root_speedup"].append(right["root_ms"] / left["root_ms"])
        ratios["root_time_ratio"].append(left["root_ms"] / right["root_ms"])
        ratios["root_p95_ratio"].append(left["root_latency_p95_us"] / right["root_latency_p95_us"])
        ratios["distinct_time_ratio"].append(left["distinct_lookup_ms"] / right["distinct_lookup_ms"])
    return {key: geomean(values) for key, values in ratios.items()}


def root_gate(metrics):
    return (metrics["root_speedup"] >= 1.05 and metrics["root_p95_ratio"] <= 1.05
            and metrics["search_time_ratio"] <= 1.05)


def decisions(trials):
    root = comparison(trials, "root-only-0", "baseline-0")
    root["passes"] = root_gate(root)
    compact = []
    for cache in (1, 4, 16):
        metrics = comparison(trials, f"compact-only-{cache}", f"baseline-{cache}")
        metrics.update(cache_mib=cache, passes=metrics["search_time_ratio"] <= 1.05)
        compact.append(metrics)
    compact_retained = all(row["passes"] for row in compact)
    combined = comparison(trials, "combined-0", "baseline-0")
    combined["passes_root_gate"] = root_gate(combined)
    # Combination must preserve the individually demonstrated root improvement.
    # If it does not, prefer the independently passing root-only change and keep
    # the compact prototype as research evidence rather than silently combining.
    if root["passes"] and compact_retained and combined["passes_root_gate"]:
        family = "combined"
    elif root["passes"]:
        family = "root-only"
    elif compact_retained:
        family = "compact-only"
    else:
        family = "baseline"
    defaults = []
    if family in ("combined", "compact-only"):
        for cache in (1, 4, 16):
            metrics = comparison(trials, f"{family}-{cache}", "baseline-0")
            metrics.update(cache_mib=cache,
                           passes=(metrics["search_speedup"] >= 1.05
                                   and metrics["distinct_time_ratio"] <= 1.05
                                   and metrics["root_time_ratio"] <= 1.05
                                   and metrics["root_p95_ratio"] <= 1.05))
            defaults.append(metrics)
    return {"root_only": root, "compact_matched_memory": compact,
            "compact_passes_all_matched_memory": compact_retained,
            "combined_zero_cache": combined, "recommended_family": family,
            "nonzero_default_candidates": defaults,
            "recommended_cache_mib": next((row["cache_mib"] for row in defaults if row["passes"]), 0)}


def dump_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True,
                        help="015 source rebuilt with this harness and ORIENT_TABLEBASE_BASELINE")
    parser.add_argument("--root-only", type=Path, required=True)
    parser.add_argument("--compact-only", type=Path, required=True)
    parser.add_argument("--combined", type=Path, required=True)
    parser.add_argument("--profile-baseline", type=Path)
    parser.add_argument("--profile-candidate", type=Path)
    parser.add_argument("--baseline-checkpoint", type=Path,
                        default=Path("artifacts/checkpoints/orient-015-syzygy/checkpoint.json"))
    parser.add_argument("--tables", type=Path, default=Path("external/tablebases/syzygy/3-4-5"))
    parser.add_argument("--fixtures", type=Path,
                        default=Path("artifacts/investigations/tablebases-001/cache/positions.fen"))
    parser.add_argument("--search-fixtures", type=Path,
                        default=Path("artifacts/investigations/tablebases-001/cache/search.fen"))
    parser.add_argument("--root-fixtures", type=Path,
                        help="defaults to the same complete covered-position corpus")
    parser.add_argument("--repeats", type=int, choices=range(1, 101), default=1)
    parser.add_argument("--out", type=Path,
                        default=Path("artifacts/investigations/tablebases-002/measurements"))
    args = parser.parse_args()
    if bool(args.profile_baseline) != bool(args.profile_candidate):
        parser.error("provide both profiling binaries or neither")
    executables = {name: getattr(args, name.replace("-", "_")).resolve(strict=True)
                   for name in ("baseline", "root-only", "compact-only", "combined")}
    for path in executables.values():
        if not path.is_file():
            parser.error("benchmark executable is not a file: " + str(path))
    fixtures = args.fixtures.resolve(strict=True)
    search_fixtures = args.search_fixtures.resolve(strict=True)
    root_fixtures = (args.root_fixtures or args.fixtures).resolve(strict=True)
    prior = json.loads(Path("artifacts/investigations/tablebases-001/cache/result.json").read_text())
    if digest(fixtures) != prior["fixtures_sha256"] or digest(search_fixtures) != prior["search_fixtures_sha256"]:
        raise ValueError("continuity fixtures differ from the first declared experiment")
    if len(fixtures.read_text().splitlines()) != 10005 or len(search_fixtures.read_text().splitlines()) != 48:
        raise ValueError("expected 10005 WDL and 48 descendant-search fixtures")
    if not root_fixtures.read_text().splitlines():
        raise ValueError("empty root fixture set")
    dataset = verify_tablebase_manifest(args.tables / "manifest.json")
    baseline_checkpoint = json.loads(args.baseline_checkpoint.read_text())
    if baseline_checkpoint.get("label") != "orient-015-syzygy":
        raise ValueError("the declared source baseline must be frozen candidate015")
    if digest(baseline_checkpoint["source_archive"]["path"]) != baseline_checkpoint["source_archive"]["sha256"]:
        raise ValueError("baseline source archive hash differs")
    args.out.mkdir(parents=True, exist_ok=False)
    cases = ([("baseline", cache) for cache in (0, 1, 4, 16)] + [("root-only", 0)]
             + [("compact-only", cache) for cache in (0, 1, 4, 16)]
             + [("combined", cache) for cache in (0, 1, 4, 16)])
    executable_records = {name: {"path": str(path), "sha256": digest(path)}
                          for name, path in executables.items()}
    record = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
              "platform": platform.platform(), "python": sys.version, "pairs": 5,
              "depth": 4, "repeats": args.repeats, "dataset": dataset,
              "fixtures": {"wdl": {"path": str(fixtures), "sha256": digest(fixtures)},
                           "search": {"path": str(search_fixtures), "sha256": digest(search_fixtures)},
                           "root": {"path": str(root_fixtures), "sha256": digest(root_fixtures)}},
              "baseline_checkpoint": {"path": str(args.baseline_checkpoint.resolve()),
                                      "sha256": digest(args.baseline_checkpoint),
                                      "source_archive": baseline_checkpoint["source_archive"]},
              "executables": executable_records,
              "case_order": [f"{name}-{cache}" for name, cache in cases],
              "profiling_baseline": "current source with legacy cache, root reuse disabled and profiling enabled; timings are diagnostic, not frozen015 acceptance timings",
              "order_rotation": "left by three cases for each successive pair",
              "cache_state": "OS cache prewarmed; fresh process/value cache per trial; no privileged flush",
              "root_caller_cache": "no whole-root cache; root TT cleared once per corpus repetition",
              "adoption": "root>=5% throughput and <=5% p95/descendant regressions; all compact matched-memory search ratios<=1.05; nonzero default additionally passes original speed/lookup/root gates"}
    dump_new(args.out / "protocol.json", record)

    def run(tool, cache, *, profiling=False):
        command = [str(tool), "experiment", dataset["root"], str(cache), str(fixtures),
                   str(search_fixtures), str(root_fixtures), "4", str(args.repeats)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800,
                                pass_fds=compute_child_fds())
        if result.returncode:
            raise RuntimeError(f"benchmark failed ({result.returncode}): {result.stderr[-4000:]}")
        measured = json.loads(result.stdout)
        if measured.get("profiling_enabled") is not profiling:
            raise ValueError("profiling and acceptance builds were mixed")
        if measured["cache_mib"] != cache or measured["repeats"] != args.repeats:
            raise ValueError("benchmark ignored requested settings")
        if measured["cache_bytes"] > cache * 1024 * 1024:
            raise ValueError("cache allocation exceeds advertised budget")
        if measured["cache_capacity"] * measured["cache_entry_bytes"] != measured["cache_bytes"]:
            raise ValueError("cache byte/capacity measurement is inconsistent")
        return measured

    with compute_lease("tablebase-optimization-paired-002"):
        warmup = run(executables["baseline"], 0)
        dump_new(args.out / "warmup.json", warmup)
        profiles = {}
        if args.profile_baseline:
            for name, tool in (("baseline", args.profile_baseline), ("candidate", args.profile_candidate)):
                tool = tool.resolve(strict=True)
                profile = run(tool, 0, profiling=True)
                if any(profile[key] != warmup[key] for key in ("lookup_hash", "search_hash", "root_hash")):
                    raise ValueError("instrumentation changed a compared result hash")
                if profile["cache_entry_bytes"] != (80 if name == "baseline" else 8):
                    raise ValueError("profiling binary uses the wrong cache representation")
                profile["binary"] = {"path": str(tool), "sha256": digest(tool)}
                profiles[name] = profile
                dump_new(args.out / ("profile-" + name + ".json"), profile)
        trials = []
        for pair in range(5):
            offset = pair * 3 % len(cases)
            for family, cache in cases[offset:] + cases[:offset]:
                case = f"{family}-{cache}"
                measured = run(executables[family], cache)
                measured.update(pair=pair + 1, case=case, family=family)
                for key in ("lookup_hash", "search_hash", "root_hash"):
                    if measured[key] != warmup[key]:
                        dump_new(args.out / f"mismatch-{pair + 1}-{case}.json", measured)
                        raise ValueError(f"{case} changed {key}; reject experiment")
                expected_entry = 8 if family in ("compact-only", "combined") else 80
                if measured["cache_entry_bytes"] != expected_entry:
                    raise ValueError(f"{family} binary uses the wrong cache representation")
                trials.append(measured)
                dump_new(args.out / f"trial-{pair + 1}-{case}.json", measured)
                print(f"pair={pair + 1} case={case} search_ms={measured['search_ms']:.3f} "
                      f"root_ms={measured['root_ms']:.3f} p95_us={measured['root_latency_p95_us']:.3f}", flush=True)
    adoption = decisions(trials)
    result = {**record, "warmup": warmup, "profiles": profiles, "trials": trials,
              "exact_result_hashes_match": True, "decision": adoption,
              "purpose": "throughput/memory measurements only; not playing-strength evidence"}
    dump_new(args.out / "result.json", result)
    print(json.dumps(adoption, indent=2))


if __name__ == "__main__":
    main()
