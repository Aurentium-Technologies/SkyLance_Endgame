#!/usr/bin/env python3
"""Five paired reader/complete-search trials; no games or training labels."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
from experiment import artifact, compute_child_fds, compute_lease, metadata, verify_artifact, write_json
from tablebase_manifest import verify_tablebase_manifest


def verify_variant(row):
    for name in ("reader", "search", "engine", "probe", "build_cache", "compile_commands"):
        verify_artifact(row[name])
    cache = Path(row["build_cache"]["path"]).read_text()
    commands = Path(row["compile_commands"]["path"]).read_text()
    for name in ("ORIENT_FATHOM_PROFILE", "ORIENT_TABLEBASE_PROFILING"):
        if re.search(r"(?m)^" + name + r":\w+=(?:ON|TRUE|YES|1)\s*$", cache, re.I):
            raise ValueError("instrumented acceptance CMake cache")
        if re.search(r"-D" + name + r"(?:=(?:1|ON|TRUE|YES))?(?=[\s\\\"]|$)", commands):
            raise ValueError("instrumented acceptance compile command")
    if row.get("profiling_enabled") is not False:
        raise ValueError("acceptance variants must disable profiling")


def geomean(values):
    values = list(values)
    if not values or any(x <= 0 or not math.isfinite(x) for x in values):
        raise ValueError("invalid paired measurement")
    return math.exp(sum(math.log(x) for x in values) / len(values))


def compare(trials, candidate):
    fields = {"reader_time_ratio": ("reader", "distinct_probe_ms"),
              "reader_cpu_ratio": ("reader", "distinct_probe_cpu_ms"),
              "reader_p95_ratio": ("reader", "probe_latency_p95_us"),
              "hot_time_ratio": ("reader", "hot_probe_ms"),
              "root_time_ratio": ("search", "root_ms"),
              "root_p95_ratio": ("search", "root_latency_p95_us"),
              "search_time_ratio": ("search", "search_ms"),
              "wdl_time_ratio": ("search", "distinct_lookup_ms"),
              "startup_ratio": ("reader", "startup_ms")}
    metrics = {}
    for name, (group, field) in fields.items():
        metrics[name] = geomean(next(r for r in trials if r["pair"] == pair and r["variant"] == candidate)[group][field]
                                / next(r for r in trials if r["pair"] == pair and r["variant"] == "baseline")[group][field]
                                for pair in range(1, 6))
    metrics["reader_throughput"] = 1 / metrics["reader_time_ratio"]
    metrics["root_throughput"] = 1 / metrics["root_time_ratio"]
    metrics["research_target_met"] = metrics["reader_time_ratio"] <= .8
    metrics["adopt"] = (metrics["reader_throughput"] >= 1.05 and metrics["root_throughput"] >= 1.05
                        and all(metrics[k] <= 1.05 for k in ("reader_p95_ratio", "root_p95_ratio",
                                                            "search_time_ratio", "wdl_time_ratio", "hot_time_ratio")))
    return metrics


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--variants", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--tables", type=Path, default=Path("external/tablebases/syzygy/3-4-5"))
    p.add_argument("--fixtures", type=Path, default=Path("artifacts/investigations/tablebases-001/cache/positions.fen"))
    p.add_argument("--search-fixtures", type=Path, default=Path("artifacts/investigations/tablebases-001/cache/search.fen"))
    p.add_argument("--repeats", type=int, default=3, choices=range(1, 101))
    args = p.parse_args()
    variants = json.loads(args.variants.read_text())
    if "baseline" not in variants or len(variants) < 2:
        raise ValueError("require baseline and at least one candidate")
    for row in variants.values():
        verify_variant(row)
    dataset = verify_tablebase_manifest(args.tables / "manifest.json")
    fixtures = artifact(args.fixtures); searches = artifact(args.search_fixtures)
    if len(args.fixtures.read_text().splitlines()) != 10005 or len(args.search_fixtures.read_text().splitlines()) != 48:
        raise ValueError("continuity requires 10005 covered and 48 six-piece positions")
    prior = json.loads(Path("artifacts/investigations/tablebases-001/cache/result.json").read_text())
    if fixtures["sha256"] != prior["fixtures_sha256"] or searches["sha256"] != prior["search_fixtures_sha256"]:
        raise ValueError("continuity fixture hashes differ")
    args.out.mkdir(parents=True, exist_ok=False)
    protocol = {"schema_version": 1, "metadata": metadata(), "variants": variants,
                "variant_manifest": artifact(args.variants), "dataset": dataset,
                "fixtures": fixtures, "search_fixtures": searches, "pairs": 5, "repeats": args.repeats,
                "cache_mib": 0, "root_search_depth": 4, "order": "rotate by one variant each pair",
                "research_target": "20 percent lower complete-adapter distinct-probe elapsed time",
                "adoption": "exact hashes; reader and complete-root throughput >=1.05x; p95, distinct WDL, hot probes and descendant-search time ratios <=1.05",
                "cache_state": "prewarmed OS pages, fresh process per sample; first reader sweep reported separately; no privileged cache flushing",
                "memory": "no adapter cache; peak RSS and glibc live heap reported; no new unbounded allocation permitted",
                "sources": {str(f): artifact(f) for f in (Path(__file__), Path("tools/benchmark_reader.cpp"), Path("tools/benchmark_tablebases.cpp"))}}
    write_json(args.out / "protocol.json", protocol)

    def invoke(cmd):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, pass_fds=compute_child_fds())
        if r.returncode:
            raise RuntimeError("benchmark failed: " + r.stderr[-4000:])
        return json.loads(r.stdout)

    def run(row):
        reader = invoke([row["reader"]["path"], dataset["root"], fixtures["path"], str(args.repeats)])
        search = invoke([row["search"]["path"], "experiment", dataset["root"], "0", fixtures["path"], searches["path"], fixtures["path"], "4", str(args.repeats)])
        if reader["profiling_enabled"] or search["profiling_enabled"] or reader["cache_bytes"] or search["cache_bytes"]:
            raise ValueError("unexpected instrumentation/cache")
        return {"reader": reader, "search": search}

    with compute_lease("reader-optimization-003-paired"):
        reference = run(variants["baseline"])
        write_json(args.out / "warmup.json", reference)
        trials = []
        names = list(variants)
        for pair in range(1, 6):
            offset = (pair - 1) % len(names)
            for name in names[offset:] + names[:offset]:
                measured = dict(run(variants[name]), pair=pair, variant=name)
                for group, keys in (("reader", ("first_hash", "distinct_hash", "hot_hash")),
                                    ("search", ("lookup_hash", "search_hash", "root_hash"))):
                    if any(measured[group][k] != reference[group][k] for k in keys):
                        write_json(args.out / f"mismatch-{pair}-{name}.json", measured)
                        raise ValueError("results changed; reject " + name)
                write_json(args.out / f"trial-{pair}-{name}.json", measured)
                trials.append(measured)
                print(f"pair={pair} variant={name} reader_ms={measured['reader']['distinct_probe_ms']:.3f} root_ms={measured['search']['root_ms']:.3f}", flush=True)
        for row in variants.values(): verify_variant(row)
        for record in (fixtures, searches, protocol["variant_manifest"], *protocol["sources"].values()):
            verify_artifact(record)
        verify_tablebase_manifest(args.tables / "manifest.json")
    decision = {name: compare(trials, name) for name in variants if name != "baseline"}
    write_json(args.out / "result.json", {**protocol, "exact_result_hashes_match": True, "trials": trials, "decision": decision})
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
