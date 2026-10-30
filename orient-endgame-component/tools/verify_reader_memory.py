#!/usr/bin/env python3
"""Exact native-order and raw-reader checks for investigation 005; no games."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

from experiment import (artifact, compute_child_fds, compute_lease, metadata,
                        verify_artifact, write_json)
from tablebase_manifest import verify_tablebase_manifest


CACHE_MIB = (0, 1, 4, 16)
SHARED_COUNTS = {"continuity": 9985, "holdout": 9975, "special": 2003}
UPSTREAM_COUNTS = {"material": 10005, "special": 2005}
NATIVE_FIELDS = {"status", "wdl", "root_status", "root_wdl", "dtz", "suggested", "moves"}
READER_FIELDS = {"line", "fen", "parse_ok", "parse_error", "status", "wdl", "dtz_status",
                 "signed_dtz", "nominal_wdl", "dtz", "root_status", "root_wdl", "root_dtz",
                 "suggested", "dtz_rounded", "moves"}
MOVE = re.compile(r"[a-h][1-8][a-h][1-8][qrbn]?\Z")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key: " + key)
        result[key] = value
    return result


def strict_json(text):
    def invalid_constant(value):
        raise ValueError("non-finite JSON constant: " + value)
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)


def verify_artifacts(value):
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            verify_artifact(value)
        for child in value.values():
            verify_artifacts(child)
    elif isinstance(value, list):
        for child in value:
            verify_artifacts(child)


def integer(value, label, low=0, high=0xffffffff):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("invalid integer " + label)


def validate_moves(row, dtz_field, ordered):
    moves = row["moves"]
    if not isinstance(moves, list):
        raise ValueError("moves must be a list")
    for move in moves:
        if not isinstance(move, list) or len(move) != 3:
            raise ValueError("move must have exactly UCI/WDL/DTZ fields")
        if not isinstance(move[0], str) or not MOVE.fullmatch(move[0]):
            raise ValueError("invalid alternative UCI")
        integer(move[1], "alternative WDL", 0, 4)
        integer(move[2], "alternative DTZ")
    names = [move[0] for move in moves]
    if len(names) != len(set(names)):
        raise ValueError("duplicate legal alternative")
    if not ordered and names != sorted(names):
        raise ValueError("raw-reader alternatives are not canonical UCI order")
    suggested = row["suggested"]
    if not isinstance(suggested, str) or (suggested != "0000" and not MOVE.fullmatch(suggested)):
        raise ValueError("invalid recommendation UCI")
    if row["root_status"] != 0:
        if moves or suggested != "0000" or row["root_wdl"] != 2 or row[dtz_field] != 0:
            raise ValueError("non-successful root has successful payload")
    elif moves:
        if suggested not in names:
            raise ValueError("recommendation missing from legal alternatives")
    elif suggested != "0000" or row[dtz_field] != 0 or row["root_wdl"] not in (0, 2):
        raise ValueError("empty successful root is not a terminal payload")


def validate_row(row, kind, index, fen, require_success=False):
    expected = NATIVE_FIELDS if kind == "native" else READER_FIELDS
    if kind not in ("native", "reader"):
        raise ValueError("unknown output schema")
    if not isinstance(row, dict) or set(row) != expected:
        raise ValueError("unexpected " + kind + " output fields")
    for field in ("status", "root_status"):
        integer(row[field], field, 0, 2)
    for field in ("wdl", "root_wdl"):
        integer(row[field], field, 0, 4)
    integer(row["dtz"], "DTZ")
    if row["status"] != 0 and row["wdl"] != 2:
        raise ValueError("non-successful WDL has successful payload")
    if require_success and (row["status"] != 0 or row["root_status"] != 0):
        raise ValueError("covered material position was not successfully probed")
    if kind == "reader":
        integer(row["line"], "line", 1)
        if row["line"] != index or row["fen"] != fen:
            raise ValueError("raw-reader FEN or line order changed")
        if row["parse_ok"] is not True or row["parse_error"] != "":
            raise ValueError("shared-valid position did not parse cleanly")
        integer(row["dtz_status"], "DTZ status", 0, 2)
        integer(row["signed_dtz"], "signed DTZ", -0x80000000, 0x7fffffff)
        integer(row["nominal_wdl"], "nominal WDL", 0, 4)
        integer(row["root_dtz"], "root DTZ")
        if abs(row["signed_dtz"]) != row["dtz"] or row["dtz_rounded"] is not None:
            raise ValueError("unexpected C++ DTZ representation or rounding metadata")
        if row["dtz_status"] != 0 and (row["signed_dtz"] != 0 or row["nominal_wdl"] != 2):
            raise ValueError("non-successful DTZ has successful payload")
        if require_success and row["dtz_status"] != 0:
            raise ValueError("covered material DTZ was not successfully probed")
    validate_moves(row, "dtz" if kind == "native" else "root_dtz", kind == "native")
    return row


def read_rows(path, kind, fens, require_success=False):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if len(lines) != len(fens):
        raise ValueError("missing or extra output rows")
    return [validate_row(strict_json(line), kind, index, fen, require_success)
            for index, (line, fen) in enumerate(zip(lines, fens), 1)]


def row_differences(reference, actual):
    if len(reference) != len(actual):
        raise ValueError("cannot compare different row counts")
    return [{"line": index, "reference": old, "actual": new}
            for index, (old, new) in enumerate(zip(reference, actual), 1) if old != new]


def require_native_order(rows):
    if not any([move[0] for move in row["moves"]] != sorted(move[0] for move in row["moves"])
               for row in rows):
        raise ValueError("native-order probe appears to sort alternatives; rebuild with preserved reader order")


def load_corpora(rows, expected):
    if not isinstance(rows, dict) or set(rows) != set(expected):
        raise ValueError("unexpected corpus names")
    result = {}
    for name, count in expected.items():
        corpus = rows[name]
        if not isinstance(corpus, dict) or type(corpus.get("positions")) is not int or corpus["positions"] != count:
            raise ValueError("unexpected corpus position count: " + name)
        verify_artifact(corpus["file"])
        fens = Path(corpus["file"]["path"]).read_text(encoding="utf-8").splitlines()
        if len(fens) != count or any(len(fen.split()) != 6 or fen != " ".join(fen.split()) for fen in fens):
            raise ValueError("corpus must contain exactly the frozen complete FEN rows: " + name)
        result[name] = fens
    if "continuity" in result and set(result["continuity"]) & set(result["holdout"]):
        raise ValueError("holdout overlaps continuity")
    return result


def validate_config(config):
    if not isinstance(config, dict) or not isinstance(config.get("variants"), dict):
        raise ValueError("configuration must contain a variant object")
    if set(config["variants"]) != {"baseline", "candidate"}:
        raise ValueError("require exactly baseline and candidate variants")
    for row in config["variants"].values():
        if not isinstance(row, dict) or not {"reader", "probe", "engine", "search"} <= set(row):
            raise ValueError("each variant needs reader, ordered probe, engine and search artifacts")
        for role in ("reader", "probe", "engine", "search"):
            verify_artifact(row[role])
    if not isinstance(config.get("upstream"), dict) or "probe" not in config["upstream"]:
        raise ValueError("configuration needs an upstream ordered probe artifact")
    verify_artifact(config["upstream"]["probe"])
    verify_artifact(config.get("tablebase_manifest"))
    verify_artifacts(config)
    return (load_corpora(config["corpora"], SHARED_COUNTS),
            load_corpora(config["upstream_corpora"], UPSTREAM_COUNTS))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    config = strict_json(args.config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("configuration must be an object")
    args.out.mkdir(parents=True, exist_ok=False)
    inputs = artifact(args.config)
    sources = {"verifier": artifact(Path(__file__)),
               "shared_tools": artifact(Path(__file__).with_name("experiment.py")),
               "dataset_verifier": artifact(Path(__file__).with_name("tablebase_manifest.py"))}
    outputs = {}; differences = []; errors = []; dataset = None

    def run(label, command, kind, fens, require_success):
        stdout = args.out / (label + ".jsonl")
        stderr = args.out / (label + ".stderr")
        details = {"argv": command, "rows_expected": len(fens), "schema": kind}
        rows = None
        try:
            with stdout.open("x", encoding="utf-8") as out, stderr.open("x", encoding="utf-8") as err:
                completed = subprocess.run(command, stdout=out, stderr=err, timeout=1200,
                                           pass_fds=compute_child_fds())
            details["exit_code"] = completed.returncode
            if completed.returncode:
                raise ValueError("probe process exited " + str(completed.returncode))
            rows = read_rows(stdout, kind, fens, require_success)
            details["rows"] = len(rows)
            details["has_nonlexicographic_alternatives"] = any(
                [move[0] for move in row["moves"]] != sorted(move[0] for move in row["moves"])
                for row in rows)
            if kind == "native" and require_success:
                require_native_order(rows)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            rows = None
            details["error"] = str(error)
            errors.append({"label": label, "error": str(error)})
        finally:
            if stdout.exists(): details["stdout"] = artifact(stdout)
            if stderr.exists(): details["stderr"] = artifact(stderr)
            outputs[label] = details
            write_json(args.out / (label + ".result.json"), details)
        print(f"checked {label}: {'valid output' if rows is not None else 'needs review'}", flush=True)
        return rows

    def compare(label, reference, actual):
        if reference is None or actual is None:
            errors.append({"label": label, "error": "comparison unavailable because a probe failed validation"})
            return
        found = row_differences(reference, actual)
        if found:
            output = args.out / (label + ".differences.json")
            write_json(output, found)
            differences.append({"label": label, "count": len(found), "details": artifact(output)})

    try:
        shared, upstream = validate_config(config)
        with compute_lease("reader-memory-005-correctness"):
            dataset = verify_tablebase_manifest(config["tablebase_manifest"]["path"])
            write_json(args.out / "protocol.json", {
                "schema_version": 1, "config": inputs, "inputs": config, "sources": sources,
                "metadata": metadata(), "dataset": dataset, "cache_mib": list(CACHE_MIB),
                "comparison": "Exact whole JSON values, recommendations and ordered alternatives; no DTZ tolerance",
                "purpose": "Correctness evidence only; not training labels or playing-strength evidence"})
            tables = dataset["root"]
            for group, fens in upstream.items():
                for cache in CACHE_MIB:
                    reference = run(f"upstream-{group}-{cache}",
                                    [config["upstream"]["probe"]["path"], tables, str(cache), config["upstream_corpora"][group]["file"]["path"]],
                                    "native", fens, group == "material")
                    for name, variant in config["variants"].items():
                        actual = run(f"upstream-{group}-{name}-{cache}",
                                     [variant["probe"]["path"], tables, str(cache), config["upstream_corpora"][group]["file"]["path"]],
                                     "native", fens, group == "material")
                        compare(f"upstream-{group}-{name}-{cache}", reference, actual)
            for group, fens in shared.items():
                for kind, role in (("reader", "reader"), ("native", "probe")):
                    reference = None
                    for name in ("baseline", "candidate"):
                        binary = config["variants"][name][role]["path"]
                        corpus = config["corpora"][group]["file"]["path"]
                        command = ([binary, tables, corpus, "verify", "1", "mmap"] if kind == "reader"
                                   else [binary, tables, "0", corpus])
                        actual = run(f"shared-{group}-{kind}-{name}", command, kind, fens, group != "special")
                        if name == "baseline": reference = actual
                        else: compare(f"shared-{group}-{kind}", reference, actual)
            verify_artifacts(config)
            verify_artifact(inputs)
            verify_artifacts(sources)
            load_corpora(config["corpora"], SHARED_COUNTS)
            load_corpora(config["upstream_corpora"], UPSTREAM_COUNTS)
            verify_tablebase_manifest(config["tablebase_manifest"]["path"])
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as error:
        errors.append({"label": "verification", "error": str(error)})

    passed = not differences and not errors
    variants = config.get("variants", {})
    variants = variants if isinstance(variants, dict) else {}
    def bindings(role):
        return {name: row.get(role) if isinstance(row, dict) else None
                for name, row in variants.items()}
    result = {"schema_version": 1, "status": "passed" if passed else "needs_review",
              "all_semantic_results_equal": passed, "exact_ordered_results_equal": passed,
              "variant_names": list(variants), "operations": ["wdl", "dtz", "all_moves"],
              "binaries": bindings("reader"), "ordered_probe_binaries": bindings("probe"),
              "engine_binaries": bindings("engine"), "search_binaries": bindings("search"),
              "upstream": config.get("upstream"), "corpora": config.get("corpora"),
              "upstream_corpora": config.get("upstream_corpora"), "cache_mib": list(CACHE_MIB),
              "tablebase_manifest": config.get("tablebase_manifest"), "dataset": dataset,
              "config": inputs, "sources": sources, "outputs": outputs,
              "differences": differences, "difference_rows": sum(item["count"] for item in differences),
              "errors": errors,
              "scope": "Exact raw reader and native ordered probe results; engine/search executable identities bound for later tests and timing, not exercised by this controller."}
    write_json(args.out / "result.json", result)
    print(json.dumps({"status": result["status"], "outputs": len(outputs),
                      "difference_rows": result["difference_rows"], "errors": len(errors)}, indent=2))
    if not passed: raise SystemExit(1)


if __name__ == "__main__": main()
