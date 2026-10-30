#!/usr/bin/env python3
"""Frozen paired catalogue-memory/startup experiment; no games or training."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import queue
import re
import shlex
import statistics
import subprocess
import threading
import time

from experiment import (artifact, compute_child_fds, compute_lease, metadata,
                        verify_artifact, write_json)
from measure_reader_comparison import (OPERATIONS, geomean, operation_repeats,
                                      validate_correctness, validate_sample,
                                      verify_artifacts, verify_corpora)
from tablebase_manifest import verify_tablebase_manifest


PHASES = ("before_init", "after_init", "after_first_probe", "after_full_sweep",
          "after_adapter_destruction", "after_explicit_teardown")
INSTRUMENTATION = ("ORIENT_FATHOM_DIAGNOSTICS", "ORIENT_FATHOM_PROFILE",
                   "ORIENT_TABLEBASE_PROFILING")
DISABLED_EXPERIMENTS = ("ORIENT_COMPACT_TABLEBASE_CACHE", "ORIENT_REUSE_ROOT_LEGAL")
SEARCH_TIMES = ("distinct_lookup_ms", "warm_lookup_ms", "search_ms", "root_ms",
                "root_latency_median_us", "root_latency_p95_us")
SEARCH_HASHES = ("lookup_hash", "search_hash", "root_hash")


def positive(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("expected finite positive " + label)
    return value


def count(value, label):
    if type(value) is not int or value < 0:
        raise ValueError("expected nonnegative integer " + label)
    return value


def alternating_orders(names, pairs=5):
    if type(pairs) is not int or pairs != 5 or len(names) != 2 or len(set(names)) != 2:
        raise ValueError("require exactly two variants and five paired trials")
    return [list(names) if i % 2 == 0 else list(reversed(names)) for i in range(pairs)]


def check_fixture(row, expected):
    verify_artifact(row["file"])
    lines = [" ".join(s.split()) for s in Path(row["file"]["path"]).read_text().splitlines() if s.strip()]
    if row.get("positions") != expected or len(lines) != expected or len(set(lines)) != expected:
        raise ValueError("unexpected fixture count or duplicate positions")
    if any(len(s.split()) != 6 for s in lines):
        raise ValueError("fixtures must retain all six FEN fields")
    return lines


def cmake_values(path):
    # Blank lines and // comments precede real entries in a CMake cache.
    # A key must never absorb documentation across a line boundary.
    return dict(re.findall(r"(?m)^([^#/:\r\n][^:\r\n]*):[^=\r\n]+=([^\r\n]*)$",
                           Path(path).read_text()))


def enabled(value):
    if value.upper() in ("ON", "TRUE", "YES"): return True
    if value.upper() in ("OFF", "FALSE", "NO", ""): return False
    try: return int(value, 0) != 0
    except ValueError: raise ValueError("unknown compile/build boolean: " + value) from None


def verify_catalog_commands(path, expected, diagnostic=False):
    records = json.loads(Path(path).read_text())
    found = set()
    for row in records:
        source = Path(row.get("file", ""))
        if "fathom-upstream" in source.parts: continue
        wanted = {"tbprobe.c", "benchmark_reader_memory.cpp"} if diagnostic else {"tbprobe.c", "reader_compare_dtz.cpp"}
        if source.name not in wanted: continue
        found.add(source.name)
        argv = row.get("arguments") or shlex.split(row.get("command", ""))
        for macro, wanted_value in (("ORIENT_FATHOM_FIVE_PIECE_CATALOG", expected),
                                    ("ORIENT_FATHOM_DIAGNOSTICS", diagnostic)):
            prefix = "-D" + macro
            values = [enabled(arg[len(prefix) + 1:]) if arg.startswith(prefix + "=") else True
                      for arg in argv if arg == prefix or arg.startswith(prefix + "=")]
            actual = values[-1] if values else False
            if len(set(values)) > 1 or actual != wanted_value:
                raise ValueError("inconsistent reader/measurement-shim compile definition: " + macro)
    required = {"tbprobe.c"} if diagnostic else {"tbprobe.c", "reader_compare_dtz.cpp"}
    if not required <= found:
        raise ValueError("missing reader or measurement-shim compile command")


def verify_variant(row, catalog=None):
    for name in ("engine", "reader", "search", "diagnostics", "build_cache", "compile_commands"):
        verify_artifact(row[name])
    if row.get("profiling_enabled") is not False or row.get("diagnostics_enabled") is not False:
        raise ValueError("acceptance instrumentation must be explicitly disabled")
    if row.get("io") != "mmap":
        raise ValueError("catalogue experiment must retain the mmap backend")
    values = cmake_values(row["build_cache"]["path"])
    if values.get("CMAKE_BUILD_TYPE") != "Release":
        raise ValueError("acceptance build must be Release")
    if values.get("ORIENT_NATIVE", "OFF").upper() not in ("ON", "TRUE", "YES", "1"):
        raise ValueError("acceptance build must retain native optimization")
    commands = Path(row["compile_commands"]["path"]).read_text()
    for name in (*INSTRUMENTATION, *DISABLED_EXPERIMENTS):
        if values.get(name, "OFF").upper() in ("ON", "TRUE", "YES", "1"):
            raise ValueError("instrumented or experimental acceptance CMake cache: " + name)
        if re.search(r"-D" + name + r"(?:=(?:1|ON|TRUE|YES))?(?=[\s\\\"]|$)", commands, re.I):
            raise ValueError("instrumented or experimental acceptance compile command: " + name)
    if values.get("ORIENT_FATHOM_PREFIX_LENGTH", "OFF").upper() not in ("ON", "TRUE", "YES", "1"):
        raise ValueError("retain the accepted prefix accelerator")
    if catalog is not None:
        if enabled(values.get("ORIENT_FATHOM_FIVE_PIECE_CATALOG", "OFF")) != catalog:
            raise ValueError("baseline/candidate catalogue build setting mismatch")
        verify_catalog_commands(row["compile_commands"]["path"], catalog)
    if "diag_build_cache" in row or "diag_compile_commands" in row:
        for field in ("diag_build_cache", "diag_compile_commands"): verify_artifact(row[field])
        diagnostic = cmake_values(row["diag_build_cache"]["path"])
        if not enabled(diagnostic.get("ORIENT_FATHOM_DIAGNOSTICS", "OFF")):
            raise ValueError("diagnostic build lacks reader counters")
        for field in ("CMAKE_CXX_COMPILER", "CMAKE_BUILD_TYPE", "ORIENT_NATIVE", "CMAKE_CXX_FLAGS",
                      "CMAKE_CXX_FLAGS_RELEASE", "CMAKE_INTERPROCEDURAL_OPTIMIZATION", "ORIENT_FATHOM_PREFIX_LENGTH"):
            if diagnostic.get(field) != values.get(field):
                raise ValueError("diagnostic build compiler/settings differ: " + field)
        if catalog is not None:
            if enabled(diagnostic.get("ORIENT_FATHOM_FIVE_PIECE_CATALOG", "OFF")) != catalog:
                raise ValueError("diagnostic catalogue setting differs from acceptance variant")
            verify_catalog_commands(row["diag_compile_commands"]["path"], catalog, diagnostic=True)
    return values


def validate_proof(proof, config):
    common = {"variants": {n: {"binary": r["reader"]} for n, r in config["variants"].items()},
              "corpora": config["corpora"], "tablebase_manifest": config["tablebase_manifest"]}
    validate_correctness(proof, common)
    if proof.get("exact_ordered_results_equal") is not True:
        raise ValueError("correctness must include exact recommendations and ordered alternatives")
    for field, role in (("engine_binaries", "engine"), ("search_binaries", "search")):
        for name, row in config["variants"].items():
            proven = proof.get(field, {}).get(name)
            if not isinstance(proven, dict):
                raise ValueError("missing correctness binding: " + field + " " + name)
            verify_artifact(proven)
            if proven["sha256"] != row[role]["sha256"]:
                raise ValueError("stale correctness binding: " + field + " " + name)


def validate_search(raw, positions, repeats, depth):
    expected = {"positions": positions, "search_positions": 48, "root_positions": positions,
                "depth": depth, "repeats": repeats, "cache_bytes": 0,
                "profiling_enabled": False}
    if any(raw.get(k) != v or (isinstance(v, int) and not isinstance(v, bool) and type(raw.get(k)) is not int)
           for k, v in expected.items()):
        raise ValueError("search workload, cache or instrumentation mismatch")
    for field in SEARCH_TIMES:
        positive(raw.get(field), field)
    if raw["root_latency_median_us"] > raw["root_latency_p95_us"]:
        raise ValueError("search percentile order is invalid")
    for field in SEARCH_HASHES:
        if not isinstance(raw.get(field), str) or not raw[field]:
            raise ValueError("missing exact search result hash")
    for field in ("search_nodes", "search_tbhits", "root_nodes", "root_tbhits", "root_fallbacks"):
        count(raw.get(field), field)
    return raw


def validate_memory(raw, positions, catalog=None):
    if (raw.get("diagnostics_enabled") is not True or raw.get("cache_bytes") != 0
            or type(raw.get("cache_bytes")) is not int or raw.get("positions") != positions):
        raise ValueError("memory diagnostics workload differs")
    if not isinstance(raw.get("semantic_hash"), str) or not raw["semantic_hash"]:
        raise ValueError("missing memory-driver result hash")
    phases = raw.get("phases", {})
    if set(phases) != set(PHASES):
        raise ValueError("memory diagnostics must preserve all lifecycle phases")
    for phase in PHASES:
        for field in ("reader_requested_live_bytes", "reader_mapped_bytes"):
            count(phases[phase].get(field), phase + " " + field)
    if catalog is not None:
        capacities = (84, 61) if catalog else (650, 861)
        for phase in ("after_init", "after_full_sweep"):
            state = phases[phase]
            if ((state.get("reader_piece_count"), state.get("reader_pawn_count")) != (84, 61)
                    or (state.get("reader_piece_capacity"), state.get("reader_pawn_capacity")) != capacities):
                raise ValueError("diagnostic reader catalogue counts/capacities mismatch")
    if phases["before_init"]["reader_requested_live_bytes"] or phases["before_init"]["reader_mapped_bytes"]:
        raise ValueError("memory driver did not start without a reader")
    for field in ("reader_requested_live_bytes", "reader_mapped_bytes"):
        if phases["after_explicit_teardown"][field] != 0:
            raise ValueError("explicit reader teardown retained " + field)
    return raw


def command_for(row, role, tables, corpus, operation, repeats, config):
    defaults = {
        "reader": ["{binary}", "{tables}", "{corpus}", "{mode}", "{repeats}", "mmap"],
        "diagnostics": ["{binary}", "{tables}", "{corpus}"],
        "search": ["{binary}", "experiment", "{tables}", "0", "{corpus}", "{search_fixture}", "{corpus}", "{depth}", "{repeats}"],
    }
    values = {"binary": row[role]["path"], "tables": str(tables), "corpus": corpus["file"]["path"],
              "mode": operation, "repeats": str(repeats), "depth": str(config["depth"]),
              "search_fixture": config["search_fixture"]["file"]["path"],
              "hot_fixture": config["hot_fixture"]["file"]["path"]}
    argv = [part.format(**values) for part in row.get(role + "_argv_template", defaults[role])]
    if not argv or argv[0] != values["binary"]:
        raise ValueError("command must invoke the pinned executable directly")
    return argv


def summarize_startup(samples, expected=20):
    if len(samples) != expected or expected != 20:
        raise ValueError("startup requires exactly twenty fresh-process samples per variant/pair")
    fields = ("constructor_ms", "configured_ready_ms", "setup_first_root_ms")
    for row in samples:
        for field in fields:
            positive(row.get(field), field)
    first = samples[0]["result"]
    if any(row["result"] != first for row in samples):
        raise ValueError("fresh-process startup queries changed results")
    return {**{field: statistics.median(row[field] for row in samples) for field in fields},
            "samples": len(samples), "result": first, "cpu_ms": None,
            "cpu_scope": "UCI setup CPU is not measured; reader first-pass CPU is saved separately"}


def memory_savings(memory_runs, baseline, candidate):
    savings = {}
    corpora = {r["corpus"] for r in memory_runs}
    if corpora != {"continuity", "holdout"}:
        raise ValueError("memory diagnostics must cover both primary corpora")
    for corpus in sorted(corpora):
        def one(name):
            rows = [r["measurement"] for r in memory_runs if r["variant"] == name and r["corpus"] == corpus]
            if len(rows) != 1:
                raise ValueError("missing or duplicate memory diagnostic")
            return rows[0]
        a, b = one(baseline), one(candidate)
        if a["semantic_hash"] != b["semantic_hash"]:
            raise ValueError("memory diagnostics changed chess results")
        savings[corpus] = {phase: a["phases"][phase]["reader_requested_live_bytes"]
                          - b["phases"][phase]["reader_requested_live_bytes"]
                          for phase in ("after_init", "after_full_sweep")}
    if not savings:
        raise ValueError("missing memory diagnostics")
    return savings


def comparison(startup_trials, trials, searches, hot_trials, memory_runs, baseline, candidate):
    def pair_ratio(rows, field, corpus=None, operation=None):
        values = []
        for pair in range(1, 6):
            found = {}
            for name in (baseline, candidate):
                selected = [r["measurement"] for r in rows if r["pair"] == pair and r["variant"] == name
                            and (corpus is None or r["corpus"] == corpus)
                            and (operation is None or r["operation"] == operation)]
                if len(selected) != 1:
                    raise ValueError("missing or duplicate paired sample")
                found[name] = positive(selected[0].get(field), field)
            values.append(found[candidate] / found[baseline])
        return geomean(values)

    ratios = {"constructor_ms": pair_ratio(startup_trials, "constructor_ms"),
              "configured_ready_ms": pair_ratio(startup_trials, "configured_ready_ms"),
              "setup_first_root_ms": pair_ratio(startup_trials, "setup_first_root_ms")}
    for corpus in ("continuity", "holdout"):
        for operation in OPERATIONS:
            for field in ("wall_ms", "cpu_ms", "p95_us", "first_pass_ms"):
                ratios[f"{corpus}/{operation}/{field}"] = pair_ratio(trials, field, corpus, operation)
        for field in SEARCH_TIMES:
            ratios[f"{corpus}/search/{field}"] = pair_ratio(searches, field, corpus)
    for field in ("wall_ms", "cpu_ms", "p95_us", "first_pass_ms"):
        ratios["hot/" + field] = pair_ratio(hot_trials, field)
    savings = memory_savings(memory_runs, baseline, candidate)
    regression_keys = ["setup_first_root_ms", "hot/wall_ms", "hot/p95_us", "hot/first_pass_ms"]
    for corpus in ("continuity", "holdout"):
        regression_keys.extend(f"{corpus}/{op}/{field}" for op in OPERATIONS
                               for field in ("wall_ms", "p95_us", "first_pass_ms"))
        regression_keys.extend(f"{corpus}/search/{field}" for field in
                               ("search_ms", "root_ms", "root_latency_p95_us"))
    gates = {
        "at_least_1mib_live_reader_saving_at_both_phases": all(v >= 1024 * 1024 for c in savings.values() for v in c.values()),
        "constructor_at_least_20_percent_faster": ratios["constructor_ms"] <= .8,
        "configured_readiness_at_least_20_percent_faster": ratios["configured_ready_ms"] <= .8,
        "all_regression_ratios_at_most_1_05": all(ratios[k] <= 1.05 for k in regression_keys),
    }
    return {"time_ratios_candidate_over_baseline": ratios, "regression_gate_keys": regression_keys,
            "memory_savings_bytes": savings,
            "gates": gates, "adopt": all(gates.values()),
            "scope": "Reader metadata/startup and unchanged query/search results; no RSS or strength adoption claim"}


def startup_uci(binary, tables, fen, options, stdout_path, stderr_path):
    """Fresh process per sample; the table-path timer excludes process launch."""
    process = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, bufsize=1, pass_fds=compute_child_fds())
    output, errors, lines = [], [], queue.Queue()

    def read_stdout():
        assert process.stdout is not None
        for line in process.stdout:
            value = line.rstrip("\n"); output.append(value); lines.put(value)
        lines.put(None)

    def read_stderr():
        assert process.stderr is not None
        errors.extend(process.stderr.readlines())

    threads = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
    for thread in threads: thread.start()

    def send(text):
        assert process.stdin is not None
        process.stdin.write(text + "\n"); process.stdin.flush()

    def until(prefix, timeout=15):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise TimeoutError("UCI timeout waiting for " + prefix)
            try: line = lines.get(timeout=remaining)
            except queue.Empty: raise TimeoutError("UCI timeout waiting for " + prefix) from None
            if line is None: raise RuntimeError("unexpected engine exit")
            if line.startswith("info string error:"): raise RuntimeError(line)
            if line.startswith(prefix): return line

    try:
        send("uci"); until("uciok")
        for name, value in options.items():
            if name.lower().startswith("syzygy"):
                raise ValueError("startup options must not preconfigure tablebases")
            send(f"setoption name {name} value {str(value).lower() if isinstance(value, bool) else value}")
        send("setoption name SyzygyCache value 0")
        send("position fen " + fen)
        send("isready"); until("readyok")
        begin = time.perf_counter_ns()
        send("setoption name SyzygyPath value " + str(tables)); send("isready")
        until("readyok")
        ready_ms = (time.perf_counter_ns() - begin) / 1e6
        previous = len(output)
        send("go depth 4"); best = until("bestmove ")
        first_root_ms = (time.perf_counter_ns() - begin) / 1e6
        infos = [line for line in output[previous:] if line.startswith("info depth ")]
        if not infos: raise ValueError("startup query returned no search information")
        info = infos[-1]
        score = re.search(r"\bscore (cp|mate) (-?\d+)", info)
        nodes = re.search(r"\bnodes (\d+)", info)
        hits = re.search(r"\btbhits (\d+)", info)
        if not score or not nodes or not hits: raise ValueError("startup query lacks exact result fields")
        result = {"bestmove": best.split()[1], "score_kind": score[1], "score": int(score[2]),
                  "nodes": int(nodes[1]), "tbhits": int(hits[1])}
        if result["tbhits"] == 0: raise ValueError("startup query did not use tablebases")
        send("quit"); process.wait(timeout=5)
        if process.returncode: raise RuntimeError("startup engine returned failure")
        return {"configured_ready_ms": ready_ms, "setup_first_root_ms": first_root_ms,
                "result": result, "cpu_ms": None}
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)
        for thread in threads: thread.join(timeout=2)
        stdout_path.write_text("\n".join(output) + "\n")
        stderr_path.write_text("".join(errors))
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream: stream.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    verify_artifacts(config); verify_corpora(config["corpora"])
    if {n: r["positions"] for n, r in config["corpora"].items()} != {"continuity": 9985, "holdout": 9975}:
        raise ValueError("retain the frozen shared-valid primary corpora")
    if config.get("startup_samples") != 20 or config.get("depth") != 4:
        raise ValueError("require twenty startup samples and depth four")
    check_fixture(config["search_fixture"], 48); check_fixture(config["hot_fixture"], 145)
    startup = check_fixture(config["startup_fixture"], 1)
    if startup[0] != config["startup_fen"]: raise ValueError("startup FEN differs from pinned fixture")
    variants, baseline, candidate = config["variants"], config["baseline"], config["candidate"]
    if set(variants) != {baseline, candidate} or baseline == candidate: raise ValueError("invalid baseline/candidate variants")
    orders = alternating_orders([baseline, candidate], config.get("pairs"))
    values = [verify_variant(variants[n], catalog=(n == candidate)) for n in (baseline, candidate)]
    for field in ("CMAKE_CXX_COMPILER", "CMAKE_BUILD_TYPE", "ORIENT_NATIVE", "CMAKE_CXX_FLAGS",
                  "CMAKE_CXX_FLAGS_RELEASE", "CMAKE_INTERPROCEDURAL_OPTIMIZATION"):
        if values[0].get(field) != values[1].get(field): raise ValueError("mismatched acceptance compiler/settings: " + field)
    proof = json.loads(Path(config["correctness"]["path"]).read_text()); validate_proof(proof, config)
    repeats = {op: operation_repeats(config, op) for op in OPERATIONS}
    if repeats != {"wdl": 20, "dtz": 10, "all_moves": 3} or config.get("search_repeats") != 3 or config.get("hot_repeats") != 96:
        raise ValueError("operation repeats differ from the frozen protocol")
    args.out.mkdir(parents=True, exist_ok=False)
    dataset = verify_tablebase_manifest(config["tablebase_manifest"]["path"])
    protocol = {"schema_version": 1, "config": artifact(args.config), "inputs": config,
                "metadata": metadata(), "dataset": dataset, "orders": orders,
                "sources": {n: artifact(Path(__file__).with_name(n)) for n in
                            (Path(__file__).name, "experiment.py", "measure_reader_comparison.py", "tablebase_manifest.py")},
                "cache_state": "OS cache prewarmed by verified collection checksums and explicit workload warmups; fresh process each call",
                "memory_scope": "requested reader allocations determine adoption; process RSS/allocator/mapped pages remain separate diagnostics",
                "cpu_scope": "reader query CPU from harness; UCI startup/search CPU unavailable, reported null",
                "gates": "memory saving >=1MiB after init/full sweep; constructor/readiness ratio<=.8; setup-first-root, primary reader wall/first-pass/p95, complete-search root/descendant/root-p95 and hot wall/p95 ratios<=1.05; exact results. CPU ratios recorded, not separate adoption gates."}
    write_json(args.out / "protocol.json", protocol)

    def invoke(name, role, corpus, operation, count_repeats, label):
        argv = command_for(variants[name], role, dataset["root"], corpus, operation, count_repeats, config)
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=1800, pass_fds=compute_child_fds())
        (args.out / (label + ".stdout")).write_text(completed.stdout)
        (args.out / (label + ".stderr")).write_text(completed.stderr)
        if completed.returncode: raise RuntimeError(f"{name} {role} failed: {label}")
        raw = json.loads(completed.stdout)
        if role != "diagnostics" and raw.get("diagnostics_enabled", False) is not False:
            raise ValueError("diagnostic counters enabled in a timing sample")
        if role == "reader": validate_sample(raw, operation, corpus["positions"], count_repeats, "mmap")
        elif role == "search": validate_search(raw, corpus["positions"], count_repeats, config["depth"])
        else: validate_memory(raw, corpus["positions"], catalog=(name == candidate))
        return raw

    reader_reference, search_reference, memory_runs, warmups = {}, {}, [], []
    startup_trials, trials, searches, hot_trials = [], [], [], []

    def exact(key, value, references):
        if references.setdefault(key, value) != value: raise ValueError("exact results changed: " + str(key))

    with compute_lease("reader-memory-startup-005"):
        for corpus_name, corpus in config["corpora"].items():
            for name in variants:
                raw = invoke(name, "diagnostics", corpus, "all_moves", 1, f"memory-{corpus_name}-{name}")
                row = {"variant": name, "corpus": corpus_name, "measurement": raw}
                write_json(args.out / f"memory-{corpus_name}-{name}.json", row); memory_runs.append(row)
                for op in OPERATIONS:
                    label = f"warmup-{corpus_name}-{op}-{name}"
                    measured = invoke(name, "reader", corpus, op, repeats[op], label)
                    exact((corpus_name, op), (measured["semantic_hash"], measured["first_pass_hash"]), reader_reference)
                    warmups.append({"variant": name, "corpus": corpus_name, "operation": op, "measurement": measured})
                    write_json(args.out / (label + ".json"), warmups[-1])
                label = f"warmup-search-{corpus_name}-{name}"
                measured = invoke(name, "search", corpus, "search", 3, label)
                exact(corpus_name, {k: measured[k] for k in SEARCH_HASHES}, search_reference)
                warmups.append({"variant": name, "corpus": corpus_name, "operation": "search", "measurement": measured})
                write_json(args.out / (label + ".json"), warmups[-1])
        for name in variants:
            label = f"warmup-hot-{name}"
            measured = invoke(name, "reader", config["hot_fixture"], "all_moves", 96, label)
            exact("hot", (measured["semantic_hash"], measured["first_pass_hash"]), reader_reference)
            warmups.append({"variant": name, "operation": "hot", "measurement": measured})
            write_json(args.out / (label + ".json"), warmups[-1])

        # Diagnostic recommendations/order are checked before timing as well
        # as in the final memory gate; no numerical tolerance is introduced.
        memory_savings(memory_runs, baseline, candidate)
        startup_reference = {}
        for pair, names in enumerate(orders, 1):
            for name in names:
                fresh = []
                for index in range(1, 21):
                    label = f"startup-{pair}-{name}-{index:02}"
                    constructor = invoke(name, "reader", config["startup_fixture"], "all_moves", 1, label + "-reader")
                    exact("constructor_root", (constructor["semantic_hash"], constructor["first_pass_hash"]), startup_reference)
                    uci = startup_uci(variants[name]["engine"]["path"], dataset["root"], config["startup_fen"],
                                      config.get("engine_options", {"Hash": 16, "Threads": 1, "Ponder": False, "Null Move": True}),
                                      args.out / (label + "-uci.stdout"), args.out / (label + "-uci.stderr"))
                    exact("uci_root", uci["result"], startup_reference)
                    row = {**uci, "constructor_ms": constructor["startup_ms"], "reader": constructor}
                    write_json(args.out / (label + ".json"), row); fresh.append(row)
                startup_row = {"pair": pair, "variant": name, "measurement": summarize_startup(fresh)}
                startup_trials.append(startup_row)
                write_json(args.out / f"startup-{pair}-{name}.json", startup_row)
                for corpus_name, corpus in config["corpora"].items():
                    for op in OPERATIONS:
                        label = f"trial-{pair}-{corpus_name}-{op}-{name}"
                        measured = invoke(name, "reader", corpus, op, repeats[op], label)
                        exact((corpus_name, op), (measured["semantic_hash"], measured["first_pass_hash"]), reader_reference)
                        row = {"pair": pair, "variant": name, "corpus": corpus_name, "operation": op, "measurement": measured}
                        write_json(args.out / (label + ".json"), row); trials.append(row)
                    label = f"trial-{pair}-{corpus_name}-search-{name}"
                    measured = invoke(name, "search", corpus, "search", 3, label)
                    exact(corpus_name, {k: measured[k] for k in SEARCH_HASHES}, search_reference)
                    row = {"pair": pair, "variant": name, "corpus": corpus_name, "measurement": measured, "cpu_ms": None}
                    write_json(args.out / (label + ".json"), row); searches.append(row)
                label = f"trial-{pair}-hot-{name}"
                measured = invoke(name, "reader", config["hot_fixture"], "all_moves", 96, label)
                exact("hot", (measured["semantic_hash"], measured["first_pass_hash"]), reader_reference)
                row = {"pair": pair, "variant": name, "measurement": measured}
                write_json(args.out / (label + ".json"), row); hot_trials.append(row)
                print(f"pair={pair} variant={name} ready_ms={startup_row['measurement']['configured_ready_ms']:.3f}", flush=True)

        verify_artifacts(config); validate_proof(proof, config); verify_corpora(config["corpora"])
        for value in (protocol["config"], *protocol["sources"].values()): verify_artifact(value)
        for name, row in variants.items(): verify_variant(row, catalog=(name == candidate))
        verify_tablebase_manifest(config["tablebase_manifest"]["path"])

    summary = comparison(startup_trials, trials, searches, hot_trials, memory_runs, baseline, candidate)
    result = {**protocol, "status": "passed", "exact_results_equal": True, "decision": summary,
              "startup_trials": startup_trials, "trials": trials, "searches": searches,
              "hot_trials": hot_trials, "memory_runs": memory_runs, "warmups": warmups}
    write_json(args.out / "result.json", result)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__": main()
