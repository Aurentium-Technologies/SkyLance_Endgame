#!/usr/bin/env python3
"""Recheck packaged comparison evidence; never execute readers or time probes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
WORKSPACE = Path(__file__).resolve().parents[2]
COMPONENT = WORKSPACE / "orient-endgame-component"
SAVED = COMPONENT / "artifacts/investigations/tablebases-004"
sys.path.insert(0, str(COMPONENT / "tools"))
from verify_reader_comparison import canonical


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    spec = importlib.util.spec_from_file_location("saved_typed_audit", SAVED / "audit_typed_values.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    performance = json.loads((SAVED / "performance/result.json").read_text())
    correctness = json.loads((SAVED / "correctness-shared/result.json").read_text())
    require(performance["status"] == "passed", "saved performance status")
    require(correctness["status"] == "passed", "saved correctness status")
    require(len(performance["trials"]) == 90 and len(performance["warmups"]) == 18, "trial counts")
    rows = moves = shared_positions = 0
    inputs = {}
    for label, group in correctness["groups"].items():
        reference = None
        for variant, details in group["outputs"].items():
            path = SAVED / "correctness-shared" / Path(details["output"]["path"]).name
            actual_hash = digest(path)
            require(actual_hash == details["output"]["sha256"], "output hash: " + path.name)
            inputs[str(path.relative_to(WORKSPACE))] = actual_hash
            values = []
            with path.open() as stream:
                for index, line in enumerate(stream, 1):
                    row = json.loads(line)
                    require(type(row["line"]) is int and row["line"] == index, "row order")
                    moves += audit.audit_row(row)
                    values.append((row["fen"], canonical(row)))
                    rows += 1
            require(len(values) == details["rows"], "corpus row count")
            if reference is None:
                reference = values
                shared_positions += len(values)
            else:
                require(values == reference, "semantic mismatch: " + label + "/" + variant)

    timings = []
    faster_pairs = 0
    for corpus in ("continuity", "holdout"):
        for operation in ("wdl", "dtz", "all_moves"):
            by_variant = {}
            for variant in ("orient016", "shakmaty_mmap"):
                samples = [t for t in performance["trials"]
                           if (t["corpus"], t["operation"], t["variant"]) == (corpus, operation, variant)]
                require(len(samples) == 5, "paired sample count")
                by_variant[variant] = {t["pair"]: t["measurement"] for t in samples}
            require(set(by_variant["orient016"]) == set(by_variant["shakmaty_mmap"]), "pair identity")
            ratios = []
            for pair, baseline in by_variant["orient016"].items():
                other = by_variant["shakmaty_mmap"][pair]
                require(baseline["calls"] == other["calls"], "query count")
                require(baseline["semantic_hash"] == other["semantic_hash"], "semantic hash")
                require(baseline["first_pass_hash"] == other["first_pass_hash"], "first pass hash")
                ratios.append(other["wall_ms"] / baseline["wall_ms"])
            ratio = math.exp(sum(map(math.log, ratios)) / len(ratios))
            reported = performance["summary"]["shakmaty_mmap"][corpus][operation]["wall_ms_ratio"]
            require(math.isclose(ratio, reported, rel_tol=1e-12, abs_tol=1e-12), "saved ratio")
            faster_pairs += sum(r > 1 for r in ratios)
            timings.append({"corpus": corpus, "operation": operation,
                            "orient_us": math.exp(sum(math.log(m["wall_ms"] * 1000 / m["calls"])
                                                     for m in by_variant["orient016"].values()) / 5),
                            "shakmaty_mmap_us": math.exp(sum(math.log(m["wall_ms"] * 1000 / m["calls"])
                                                            for m in by_variant["shakmaty_mmap"].values()) / 5),
                            "orient_throughput_ratio": ratio,
                            "pair_ratio_min": min(ratios), "pair_ratio_max": max(ratios)})
    require((rows, moves, shared_positions, faster_pairs) == (65889, 916500, 21963, 30), "audit totals")
    matching = []
    for name in ("src/tablebases.cpp", "include/orient/tablebases.hpp", "src/chess.cpp",
                 "include/orient/chess.hpp", "tools/reader_compare.cpp", "tools/reader_compare_dtz.cpp"):
        require(digest(COMPONENT / name) == digest(SAVED / "orient016-source" / name), "retained source: " + name)
        matching.append(name)
    result = {"status": "passed", "checked_date_nz": "2026-10-29",
              "scope": "Reaudit of saved 2026-10-28 benchmark/correctness outputs; no new timed probes or builds",
              "shared_positions": shared_positions, "typed_rows": rows, "move_records": moves,
              "mmap_pairs_favouring_orient": faster_pairs, "timings": timings,
              "current_files_equal_to_frozen_004": matching,
              "reader_source_sha256": digest(COMPONENT / "third_party/fathom/src/tbprobe.c"),
              "reader_source_note": "Current source additionally includes default-OFF experiment 005; retained 016 behavior, not identical entire source.",
              "inputs_sha256": inputs,
              "performance_result_sha256": digest(SAVED / "performance/result.json")}
    output = Path(__file__).with_name("current-evidence-audit.json")
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "scope", "shared_positions", "typed_rows", "move_records", "mmap_pairs_favouring_orient")}))


if __name__ == "__main__":
    main()
