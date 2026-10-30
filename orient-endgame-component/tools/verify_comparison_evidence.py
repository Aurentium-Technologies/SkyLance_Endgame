#!/usr/bin/env python3
"""Recompute frozen 006 numeric claims from published raw data, without readers.

Requires NumPy for the original whole-block bootstrap and latency calculations.
The pinned original auditor supplies the independent mathematical implementation;
its binary/source-preservation entry point is deliberately not executed.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
from pathlib import Path
import sys

from verify_public_evidence import digest, local_file, read_json, verify_manifest


AUDITOR_SHA256 = "c75d3538333dc02aa4a917d2fb56d0373d3abe44088c50660d3360fd4807c034"
CAMPAIGN = Path("artifacts/investigations/tablebases-006")
NAMES = ("orient", "fathom", "pyrrhic_c", "shakmaty", "pyrrhic_rs", "stockfish")
OPERATIONS = ("wdl", "dtz", "all_moves")
REPEATS = {"wdl": 20, "dtz": 10, "all_moves": 3}
THRESHOLDS = {"alpha": .05, "bootstrap_resamples": 100000, "family": 30,
              "p95_upper": 1.05, "wall_upper": .95}
GROUPS = {"archived_continuity": 9985, "archived_holdout": 9975,
          "archived_special": 2003, "primary": 11000, "special006": 446}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def validate_protocol(freeze):
    need(freeze.get("seed") == 2026102906 and freeze.get("blocks") == 30
         and freeze.get("samples") == 540 and freeze.get("repeats") == REPEATS,
         "frozen sample count, repeats or seed differs")
    need(freeze.get("thresholds") == THRESHOLDS, "frozen statistical thresholds differ")
    need(set(freeze.get("binaries", {})) == set(NAMES), "frozen reader roster differs")


class Evidence:
    def __init__(self, root, manifest):
        self.root = Path(root).resolve(strict=True)
        self.component = self.root / "orient-endgame-component"
        self.original = Path(manifest.get("original_component_root", ""))
        need(self.original.is_absolute(), "missing original component path")
        self.members = {row["path"] for row in manifest["files"]}

    def resolve(self, *parts):
        path = Path(*parts)
        if path.is_absolute() and path.is_relative_to(self.original):
            path = self.component / path.relative_to(self.original)
        elif not path.is_absolute():
            path = self.component / path
        need(path.is_relative_to(self.root), "path outside comparison evidence")
        name = path.relative_to(self.root).as_posix()
        need(name in self.members, "audit input is not in the verified inventory: " + name)
        return local_file(self.root, name)

    def campaign_file(self, name):
        return self.resolve(self.component / CAMPAIGN / name)


def load_auditor(evidence):
    path = evidence.campaign_file("final_audit.py")
    need(digest(path) == AUDITOR_SHA256, "original independent auditor SHA-256 differs")
    spec = importlib.util.spec_from_file_location("skylance_frozen_006_auditor", path)
    need(spec is not None and spec.loader is not None, "cannot load original independent auditor")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    module.Path = evidence.resolve
    module.HERE = evidence.component / CAMPAIGN
    module.ROOT = evidence.component
    module.load = lambda path: read_json(evidence.resolve(path))
    return module


def check_summaries(auditor, evidence, analysis):
    """Check the saved CSV/histogram numbers without importing report.py."""
    run = evidence.component / CAMPAIGN / "performance/run001"
    aggregate, material = analysis["aggregate"], analysis["material"]
    with evidence.resolve(run / "timing-summary.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    need(len(rows) == 18 and len({(r["variant"], r["operation"]) for r in rows}) == 18,
         "aggregate summary group count differs")
    for row in rows:
        values = aggregate[row["variant"], row["operation"]]
        expected = {
            "wall_us_per_query": auditor.geometric(r["wall_ms"] * 1000 / r["calls"] for r in values),
            "cpu_us_per_query": auditor.geometric(r["cpu_ms"] * 1000 / r["calls"] for r in values),
            "table_setup_ms": auditor.geometric(r["startup_ms"] for r in values),
            "first_pass_ms": auditor.geometric(r["first_pass_ms"] for r in values),
            "process_peak_mib": auditor.geometric(r["peak_rss_kib"] / 1024 for r in values),
            "process_peak_mib_min": min(r["peak_rss_kib"] / 1024 for r in values),
            "process_peak_mib_max": max(r["peak_rss_kib"] / 1024 for r in values),
            "minimum_query_us": min(r["minimum_us"] for r in values),
            "maximum_query_us": max(r["maximum_us"] for r in values)}
        expected.update({p: auditor.geometric(r[p] for r in values) for p in ("p50_us", "p95_us", "p99_us")})
        for field, value in expected.items():
            auditor.close(value, float(row[field]), "aggregate CSV " + field)
    with evidence.resolve(run / "per-material.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    need(len(rows) == 1980 and len({(r["variant"], r["operation"], r["material"]) for r in rows}) == 1980,
         "material summary group count differs")
    for row in rows:
        name, operation, label = row["variant"], row["operation"], row["material"]
        values, baseline = material[name, operation, label], material["orient", operation, label]
        need(int(row["root_positions"]) == 100 and int(row["blocks"]) == 30
             and int(row["total_calls"]) == sum(r["calls"] for r in values), "material counts differ")
        expected = {
            "mean_query_us_geomean": auditor.geometric(r["mean_us"] for r in values),
            "p50_query_us_geomean": auditor.geometric(r["p50_us"] for r in values),
            "p95_query_us_geomean": auditor.geometric(r["p95_us"] for r in values),
            "orient_over_variant_mean_query_ratio": auditor.geometric(a["mean_us"] / b["mean_us"] for a, b in zip(baseline, values))}
        for field, value in expected.items():
            auditor.close(value, float(row[field]), "material CSV " + field)
    distributions = read_json(evidence.resolve(run / "latency-distributions.json"))
    need(distributions["bin_edges_us"] == [None if x == float("inf") else float(x) for x in auditor.EDGES],
         "histogram edges differ")
    groups = distributions["groups"]
    need(len(groups) == 18 and len({(r["variant"], r["operation"]) for r in groups}) == 18,
         "histogram group count differs")
    for row in groups:
        need(row["counts"] == analysis["histograms"][row["variant"], row["operation"]].tolist(),
             "raw histogram counts differ")
    return {"aggregate_groups": 18, "material_groups": 1980, "histogram_groups": 18}


def audit(root):
    manifest, checked = verify_manifest(root, "EVIDENCE-MANIFEST.json", "skylance-006-comparison-evidence")
    evidence = Evidence(root, manifest)
    # All required inputs are inventory-checked before the pinned auditor loads.
    freeze = read_json(evidence.campaign_file("protocol/freeze.json"))
    result = read_json(evidence.campaign_file("performance/run001/result.json"))
    read_json(evidence.campaign_file("performance/run001/statistics.json"))
    validate_protocol(freeze)
    need(result.get("status") == "complete", "primary campaign is incomplete")
    auditor = load_auditor(evidence)
    need(auditor.check_record(result["freeze"]) == evidence.campaign_file("protocol/freeze.json"),
         "primary result has a different source/input freeze")
    start = read_json(evidence.campaign_file("performance/run001/start.json"))
    need(start["freeze"] == result["freeze"], "start/end freeze differs")
    proof = read_json(auditor.check_record(freeze["correctness"]))
    auditor.check_record(freeze["dataset"])
    need(proof.get("status") == "passed" and proof.get("all_semantic_results_equal") is True,
         "correctness proof failed")
    need(proof["binaries"] == freeze["binaries"] and proof["dataset"] == freeze["dataset"],
         "correctness binary/dataset record binding differs")
    need({name: row["rows"] for name, row in proof["groups"].items()} == GROUPS,
         "correctness corpus inventory differs")
    correctness = auditor.check_correctness(proof)
    primary, mapping, block_fens = auditor.material_inputs(freeze)
    run = evidence.component / CAMPAIGN / "performance/run001"
    for operation in OPERATIONS:
        hashes = None
        for name in NAMES:
            raw = read_json(evidence.resolve(run / ("warmup-" + operation + "-" + name + ".json")))
            auditor.sample_shape(raw, operation)
            need(read_json(evidence.resolve(run / ("warmup-" + operation + "-" + name + ".stdout"))) == raw,
                 "warmup raw output differs")
            need(evidence.resolve(run / ("warmup-" + operation + "-" + name + ".stdout.stderr")).read_bytes() == b"",
                 "nonempty warmup stderr")
            current = raw["semantic_hash"], raw["first_pass_hash"]
            if hashes is None:
                hashes = current
            need(current == hashes, "warmup cross-reader result hashes differ")
    analysis = auditor.independently_analyse(result, freeze, run, mapping, block_fens)
    summaries = check_summaries(auditor, evidence, analysis)
    wins = sum(row["verdict"] == "supported_win" for row in analysis["comparisons"])
    return {"status": "passed", **checked, "primary_samples": 540, "warmups": 18,
            "primary_positions": len(primary), "material_classes": len(set(mapping.values())),
            "correctness": correctness, "summaries": summaries, "bootstrap_resamples": 100000,
            "bootstrap_seed": 2026102906, "bootstrap_unit": "whole block", "family_size": 30,
            "supported_wins": wins, "comparisons": 15,
            "all_roster_superiority": analysis["all_roster_superiority"],
            "comparison_results": analysis["comparisons"], "numpy_version": analysis["numpy_version"],
            "scope": "Published raw numeric/correctness audit only; no reader execution, table-data checks, source-archive preservation or existence/hash validation of excluded historical binaries/engine source",
            "unpublished_bindings": "Original binary/source references and hashes remain recorded in freeze.json and UNPUBLISHED-BINDINGS.json; their payloads are deliberately excluded"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    # Avoid an unrelated NumPy BLAS pool; this verifier does not run benchmarks.
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    try:
        if args.out and args.out.exists():
            raise ValueError("refusing to overwrite an audit result")
        result = audit(args.bundle_root)
        text = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.out:
            with args.out.open("x", encoding="utf-8") as stream:
                stream.write(text)
        print(text, end="")
    except (OSError, ValueError, TypeError, KeyError, ImportError) as error:
        print("Comparison evidence verification failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
