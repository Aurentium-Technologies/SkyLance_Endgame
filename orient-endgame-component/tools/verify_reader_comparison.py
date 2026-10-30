#!/usr/bin/env python3
"""Exact board/clock semantic comparison; no games or training labels."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
from experiment import artifact, compute_child_fds, compute_lease, verify_artifact, write_json
from tablebase_manifest import verify_tablebase_manifest
from verify_reader_memory import strict_json, verify_artifacts


def canonical(row):
    if any(row[k] not in (0, 1, 2) for k in ("status", "dtz_status", "root_status")):
        raise ValueError("invalid probe status")
    moves = row["moves"]
    if len({m[0] for m in moves}) != len(moves) or moves != sorted(moves):
        raise ValueError("duplicate or noncanonical legal alternatives")
    if any(m[1] not in range(5) or m[2] < 0 for m in moves):
        raise ValueError("invalid move value")
    if row["root_status"] == 0 and row["suggested"] != "0000" and row["suggested"] not in {m[0] for m in moves}:
        raise ValueError("illegal reader recommendation")
    return (row["parse_ok"], row["status"], row["wdl"] if row["status"] == 0 else None,
            row["dtz_status"], (row["signed_dtz"], row["nominal_wdl"], row["dtz"]) if row["dtz_status"] == 0 else None,
            row["root_status"], (row["root_wdl"], row["root_dtz"], moves) if row["root_status"] == 0 else None)


def load_corpora(config):
    """Bind nonempty comparisons to their actual pinned input rows."""
    variants = config.get("variants") if isinstance(config, dict) else None
    corpora = config.get("corpora") if isinstance(config, dict) else None
    if not isinstance(variants, dict) or len(variants) < 2:
        raise ValueError("require at least two reader variants")
    if not isinstance(corpora, dict) or not corpora:
        raise ValueError("require nonempty correctness corpora")
    for name in (*variants, *corpora):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("reader and corpus names must be safe output labels")
    for row in variants.values():
        if not isinstance(row, dict) or row.get("io") not in ("mmap", "pread"):
            raise ValueError("declare each reader's I/O backend")
        verify_artifact(row.get("binary"))
    verify_artifact(config.get("tablebase_manifest"))
    verify_artifacts(config)
    result = {}
    for name, corpus in corpora.items():
        if (not isinstance(corpus, dict) or type(corpus.get("positions")) is not int
                or corpus["positions"] <= 0):
            raise ValueError("correctness corpus must contain a positive position count")
        verify_artifact(corpus.get("file"))
        fens = Path(corpus["file"]["path"]).read_text(encoding="utf-8").splitlines()
        if len(fens) != corpus["positions"] or any(
                len(fen.split()) != 6 or fen != " ".join(fen.split()) for fen in fens):
            raise ValueError("correctness corpus differs from its declared complete FEN rows")
        result[name] = fens
    return result


def validate_output_rows(rows, fens):
    if len(rows) != len(fens):
        raise ValueError("missing correctness rows")
    for index, (row, fen) in enumerate(zip(rows, fens), 1):
        if (not isinstance(row, dict) or type(row.get("line")) is not int
                or row["line"] != index or row.get("fen") != fen):
            raise ValueError("correctness output differs from the pinned fixture order")
        if type(row.get("parse_ok")) is not bool:
            raise ValueError("reader parse status must be a JSON boolean")
        # Canonicalization defines which returned values are compared; validate
        # every variant, including the reference, before accepting the output.
        canonical(row)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(); config = strict_json(args.config.read_text(encoding="utf-8"))
    fens_by_corpus = load_corpora(config)
    args.out.mkdir(parents=True, exist_ok=False)
    dataset = verify_tablebase_manifest(config["tablebase_manifest"]["path"])
    for v in config["variants"].values(): verify_artifact(v["binary"])
    all_equal = True; groups = {}; differences = []
    with compute_lease("reader004-semantic-comparison"):
        for label, corpus in config["corpora"].items():
            verify_artifact(corpus["file"])
            reference = None; details = {}; recommendations = Counter()
            for name, variant in config["variants"].items():
                cmd = [variant["binary"]["path"], dataset["root"], corpus["file"]["path"], "verify", "1", variant["io"]]
                stdout = args.out / f"{label}-{name}.jsonl"; stderr = args.out / f"{label}-{name}.stderr"
                with stdout.open("w") as out, stderr.open("w") as err:
                    result = subprocess.run(cmd, stdout=out, stderr=err, timeout=1200, pass_fds=compute_child_fds())
                if result.returncode: raise RuntimeError(f"{name} verification failed; see {stderr}")
                rows = validate_output_rows(
                    [strict_json(line) for line in stdout.read_text(encoding="utf-8").splitlines()],
                    fens_by_corpus[label])
                if reference is None: reference = rows
                mismatches = 0; rounded = 0
                for index, (old, row) in enumerate(zip(reference, rows), 1):
                    if row["fen"] != old["fen"] or row["line"] != index:
                        raise ValueError("correctness fixture order changed")
                    if canonical(old) != canonical(row):
                        differences.append({"corpus": label, "variant": name, "line": index, "orient": old, "other": row})
                        mismatches += 1; all_equal = False
                    if row.get("root_rounded"): rounded += 1
                    if row["suggested"] != old["suggested"]:
                        recommendations[name] += 1
                details[name] = {"rows": len(rows), "strict_semantic_mismatches": mismatches,
                                 "rounded_roots": rounded, "output": artifact(stdout)}
                print(f"corpus={label} reader={name} rows={len(rows)} semantic_mismatches={mismatches}", flush=True)
            groups[label] = {"outputs": details, "different_recommendations": dict(recommendations)}
        load_corpora(config)
        verify_tablebase_manifest(config["tablebase_manifest"]["path"])
    result = {"schema_version": 1, "status": "passed" if all_equal else "needs_review",
              "all_semantic_results_equal": all_equal, "variant_names": list(config["variants"]),
              "operations": ["wdl", "dtz", "all_moves"],
              "binaries": {name: v["binary"] for name, v in config["variants"].items()},
              "corpora": config["corpora"], "tablebase_manifest": config["tablebase_manifest"],
              "groups": groups, "config": artifact(args.config), "verifier": artifact(Path(__file__)),
              "scope": "Strict raw WDL, signed nominal DTZ, clock-derived nominal WDL and complete legal-alternative values. Recommendations/rounding flags reported separately; no arbitrary +/-1 allowance."}
    write_json(args.out / "differences.json", differences)
    write_json(args.out / "result.json", result)
    print(json.dumps({"status": result["status"], "differences": len(differences)}, indent=2))
    if not all_equal: raise SystemExit(1)


if __name__ == "__main__": main()
