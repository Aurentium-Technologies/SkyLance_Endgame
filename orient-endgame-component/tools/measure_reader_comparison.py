#!/usr/bin/env python3
"""Paired external-reader measurements; no games, training or engine integration.

The executable command is supplied as an argv template in a pinned configuration.
Each invocation measures one operation on one corpus, in a fresh process. Reader
adapters must expose the same normalized result contract before this runner is
used; the pinned correctness report is a precondition, not a timing result.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess

from experiment import (artifact, compute_child_fds, compute_lease, metadata,
                        verify_artifact, write_json)
from tablebase_manifest import verify_tablebase_manifest


OPERATIONS = ("wdl", "dtz", "all_moves")
REQUIRED_METRICS = ("wall_ms", "cpu_ms", "p50_us", "p95_us")
RATIO_METRICS = (*REQUIRED_METRICS, "startup_ms", "first_pass_ms", "peak_rss_kib")


def geomean(values):
    values = list(values)
    if not values or any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("paired ratios require finite positive values")
    return math.exp(sum(math.log(v) for v in values) / len(values))


def rotated_orders(names, pairs=5):
    names = list(names)
    if len(names) < 2 or len(names) != len(set(names)):
        raise ValueError("require at least two distinct reader variants")
    if pairs != 5:
        raise ValueError("this comparison requires five paired trials")
    return [names[i % len(names):] + names[:i % len(names)] for i in range(pairs)]


def verify_artifacts(value):
    """Check every explicit artifact recursively; do not open other path strings."""
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            verify_artifact(value)
        for child in value.values():
            verify_artifacts(child)
    elif isinstance(value, list):
        for child in value:
            verify_artifacts(child)


def verify_corpora(corpora):
    if set(corpora) != {"continuity", "holdout"}:
        raise ValueError("require distinct continuity and fresh holdout corpora")
    seen = {}
    for name, row in corpora.items():
        if type(row.get("positions")) is not int or row["positions"] <= 0:
            raise ValueError("corpora must declare a positive position count")
        verify_artifact(row["file"])
        lines = [" ".join(line.split()) for line in Path(row["file"]["path"]).read_text().splitlines() if line.strip()]
        if any(len(line.split()) != 6 for line in lines):
            raise ValueError("all positions must retain all six FEN fields")
        if len(lines) != row["positions"] or len(lines) != len(set(lines)):
            raise ValueError("corpus size or uniqueness differs from frozen configuration")
        seen[name] = set(lines)
    if seen["continuity"] & seen["holdout"]:
        raise ValueError("holdout overlaps the continuity corpus")


def operation_repeats(config, operation):
    if operation not in OPERATIONS:
        raise ValueError("unknown reader operation")
    default = config.get("repeats", 3)
    overrides = config.get("repeats_by_operation", {})
    if (type(default) is not int or not 1 <= default <= 100
            or not isinstance(overrides, dict) or not set(overrides) <= set(OPERATIONS)):
        raise ValueError("invalid operation repeat configuration")
    if any(type(value) is not int or not 1 <= value <= 100 for value in overrides.values()):
        raise ValueError("operation repeats must be integers in 1..100")
    return overrides.get(operation, default)


def validate_correctness(correctness, config):
    """Bind a passed comparison to the exact timed executable/data contents."""
    verify_artifacts(correctness)
    if correctness.get("status") != "passed" or correctness.get("all_semantic_results_equal") is not True:
        raise ValueError("correctness gate has not passed")
    if not set(config["variants"]) <= set(correctness.get("variant_names", [])):
        raise ValueError("correctness gate covers different readers")
    if not set(OPERATIONS) <= set(correctness.get("operations", [])):
        raise ValueError("correctness gate does not cover all operations")

    def same_digest(proven, requested, label):
        if not isinstance(proven, dict) or "sha256" not in proven:
            raise ValueError("missing correctness binding: " + label)
        verify_artifact(proven)
        verify_artifact(requested)
        # Identical verified copies are equivalent; absolute path spelling is
        # not part of executable or corpus identity.
        if proven["sha256"] != requested["sha256"]:
            raise ValueError("stale correctness binding: " + label)

    for name, variant in config["variants"].items():
        same_digest(correctness.get("binaries", {}).get(name), variant["binary"], "binary " + name)
    for name, corpus in config["corpora"].items():
        proven = correctness.get("corpora", {}).get(name, {})
        same_digest(proven.get("file"), corpus["file"], "corpus " + name)
        if proven.get("positions") != corpus["positions"]:
            raise ValueError("stale correctness corpus count: " + name)
    same_digest(correctness.get("tablebase_manifest"), config["tablebase_manifest"], "dataset manifest")


def validate_sample(raw, operation, positions, repeats, backend=None):
    if not isinstance(raw, dict):
        raise ValueError("reader must return one JSON object")
    if raw.get("mode") != operation or raw.get("positions") != positions or raw.get("repeats") != repeats:
        raise ValueError("reader ignored requested workload")
    if raw.get("calls") != positions * repeats:
        raise ValueError("top-level operation count differs")
    if raw.get("profiling_enabled") is not False:
        raise ValueError("acceptance measurements must disable profiling")
    if raw.get("backend") not in ("mmap", "pread") or (backend is not None and raw["backend"] != backend):
        raise ValueError("reader used an unexpected I/O backend")
    if "cache_bytes" in raw and (type(raw["cache_bytes"]) is not int or raw["cache_bytes"] != 0):
        raise ValueError("reader enabled an unrequested result cache")
    if not isinstance(raw.get("semantic_hash"), str) or not raw["semantic_hash"]:
        raise ValueError("missing normalized semantic hash")
    for field in REQUIRED_METRICS:
        value = raw.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("invalid required timing metric: " + field)
    if raw["p50_us"] > raw["p95_us"]:
        raise ValueError("p50 exceeds p95")
    for field in ("startup_ms", "first_pass_ms", "first_pass_cpu_ms", "peak_rss_kib"):
        value = raw.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid resource metric: " + field)
    return raw


def paired_comparison(trials, baseline, candidate, corpus, operation):
    def one(pair, variant):
        found = [r for r in trials if (r["pair"], r["variant"], r["corpus"], r["operation"])
                 == (pair, variant, corpus, operation)]
        if len(found) != 1:
            raise ValueError("missing or duplicate paired measurement")
        return found[0]["measurement"]

    ratios = {}
    for field in RATIO_METRICS:
        pairs = [(one(i, candidate)[field], one(i, baseline)[field]) for i in range(1, 6)]
        # Tiny startup counters or unavailable resource values may legitimately
        # be zero. Retain the raw values and leave that ratio unavailable.
        ratios[field + "_ratio"] = (geomean(a / b for a, b in pairs)
                                    if all(a > 0 and b > 0 for a, b in pairs) else None)
    ratios["throughput_ratio"] = 1 / ratios["wall_ms_ratio"]
    ratios["wall_time_reduction_percent"] = 100 * (1 - ratios["wall_ms_ratio"])
    ratios["interpretation"] = "candidate/baseline time ratios; no engine-strength inference"
    return ratios


def command_for(variant, tables, corpus, operation, repeats):
    replacements = {"binary": variant["binary"]["path"], "tables": str(tables),
                    "corpus": corpus["file"]["path"], "mode": operation, "repeats": str(repeats)}
    command = [part.format(**replacements) for part in variant["argv_template"]]
    if not command or command[0] != replacements["binary"]:
        raise ValueError("command must invoke the pinned executable directly")
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    verify_artifacts(config)
    verify_corpora(config["corpora"])
    if config.get("pairs") != 5:
        raise ValueError("require five paired trials")
    repeats = {op: operation_repeats(config, op) for op in OPERATIONS}
    variants = config["variants"]
    baseline = config["baseline"]
    if baseline not in variants:
        raise ValueError("baseline is absent")
    order = rotated_orders(variants)
    for row in variants.values():
        if row.get("profiling_enabled") is not False:
            raise ValueError("profiling must be explicitly disabled")
        if row.get("io") not in ("mmap", "pread"):
            raise ValueError("declare reader I/O mode explicitly")
    correctness = json.loads(Path(config["correctness"]["path"]).read_text())
    validate_correctness(correctness, config)
    dataset = verify_tablebase_manifest(config["tablebase_manifest"]["path"])
    args.out.mkdir(parents=True, exist_ok=False)
    protocol = {"schema_version": 1, "config": artifact(args.config), "inputs": config,
                "dataset": dataset, "metadata": metadata(), "orders": order,
                "repeats_by_operation": repeats,
                "sources": {"runner": artifact(Path(__file__)),
                            "shared_tools": artifact(Path(__file__).with_name("experiment.py"))},
                "cache_state": "dataset checksums and explicit warmups prewarm OS cache; fresh process per measurement; first pass reported separately",
                "memory_scope": "whole-process peak RSS; mmap/pread page-cache accounting differs; not reader-only allocated memory",
                "interpretation": "external reader comparison only; no engine integration, training data or games"}
    write_json(args.out / "protocol.json", protocol)

    def run(variant_name, corpus_name, operation, prefix):
        row = variants[variant_name]
        corpus = config["corpora"][corpus_name]
        command = command_for(row, dataset["root"], corpus, operation, repeats[operation])
        completed = subprocess.run(command, capture_output=True, text=True, timeout=1800,
                                   pass_fds=compute_child_fds())
        (args.out / (prefix + ".stdout")).write_text(completed.stdout)
        (args.out / (prefix + ".stderr")).write_text(completed.stderr)
        if completed.returncode:
            raise RuntimeError(f"reader command failed: {variant_name}, exit {completed.returncode}")
        measured = validate_sample(json.loads(completed.stdout), operation, corpus["positions"], repeats[operation], row["io"])
        return measured

    trials = []
    warmups = []
    reference = {}
    with compute_lease("external-reader-comparison-004"):
        for corpus_name in config["corpora"]:
            for operation in OPERATIONS:
                for name in variants:
                    warm = run(name, corpus_name, operation, f"warmup-{corpus_name}-{operation}-{name}")
                    warm_row = {"variant": name, "corpus": corpus_name, "operation": operation,
                                "measurement": warm}
                    write_json(args.out / f"warmup-{corpus_name}-{operation}-{name}.json", warm_row)
                    warmups.append(warm_row)
                    key = (corpus_name, operation)
                    previous = reference.setdefault(key, warm["semantic_hash"])
                    if previous != warm["semantic_hash"]:
                        raise ValueError("normalized answers disagree during warmup")
        for pair, names in enumerate(order, 1):
            for name in names:
                for corpus_name in config["corpora"]:
                    for operation in OPERATIONS:
                        label = f"trial-{pair}-{corpus_name}-{operation}-{name}"
                        measured = run(name, corpus_name, operation, label)
                        row = {"pair": pair, "variant": name, "corpus": corpus_name,
                               "operation": operation, "measurement": measured}
                        write_json(args.out / (label + ".json"), row)
                        if measured["semantic_hash"] != reference[(corpus_name, operation)]:
                            raise ValueError("normalized answers changed during paired trials")
                        trials.append(row)
                        print(f"pair={pair} corpus={corpus_name} operation={operation} reader={name} wall_ms={measured['wall_ms']:.3f}", flush=True)
        verify_artifacts(config)
        validate_correctness(correctness, config)
        verify_corpora(config["corpora"])
        for value in (protocol["config"], *protocol["sources"].values()): verify_artifact(value)
        verify_tablebase_manifest(config["tablebase_manifest"]["path"])
    summary = {name: {corpus: {op: paired_comparison(trials, baseline, name, corpus, op)
                              for op in OPERATIONS} for corpus in config["corpora"]}
               for name in variants if name != baseline}
    write_json(args.out / "result.json", {**protocol, "status": "passed", "trials": trials,
                                         "warmups": warmups,
                                         "normalized_hashes_equal": True, "summary": summary})
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
