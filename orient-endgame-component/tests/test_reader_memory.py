"""Memory/startup experiment gates and provenance, without running engines."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from experiment import artifact
from measure_reader_memory import (PHASES, SEARCH_HASHES, SEARCH_TIMES, alternating_orders,
                                   check_fixture, command_for, comparison, memory_savings,
                                   summarize_startup, validate_memory, validate_proof,
                                   validate_search, verify_variant, startup_uci, verify_catalog_commands,
                                   cmake_values)


def memory(live=3 * 1024 * 1024):
    phases = {name: {"reader_requested_live_bytes": live, "reader_mapped_bytes": 1000000000}
              for name in PHASES}
    for name in ("before_init", "after_explicit_teardown"):
        phases[name] = {"reader_requested_live_bytes": 0, "reader_mapped_bytes": 0}
    return {"diagnostics_enabled": True, "cache_bytes": 0, "positions": 9985,
            "semantic_hash": "reader-results", "phases": phases, "peak_rss_kib": 1}


def search(positions=9985):
    return {"positions": positions, "search_positions": 48, "root_positions": positions,
            "depth": 4, "repeats": 3, "cache_bytes": 0, "profiling_enabled": False,
            **{k: 100. for k in SEARCH_TIMES}, **{k: "exact-" + k for k in SEARCH_HASHES},
            **{k: 100 for k in ("search_nodes", "search_tbhits", "root_nodes", "root_tbhits", "root_fallbacks")}}


def fixtures(ratio=.99):
    startup, readers, searches, hot, memories = [], [], [], [], []
    for pair in range(1, 6):
        for name in ("baseline", "candidate"):
            r = 1. if name == "baseline" else ratio
            startup.append({"pair": pair, "variant": name, "measurement": {
                "constructor_ms": 4. if name == "baseline" else 2.,
                "configured_ready_ms": 4. if name == "baseline" else 2.,
                "setup_first_root_ms": 100 * r}})
            for corpus in ("continuity", "holdout"):
                for op in ("wdl", "dtz", "all_moves"):
                    readers.append({"pair": pair, "variant": name, "corpus": corpus, "operation": op,
                                    "measurement": {k: 100 * r for k in ("wall_ms", "cpu_ms", "p95_us", "first_pass_ms")}})
                searches.append({"pair": pair, "variant": name, "corpus": corpus,
                                 "measurement": {k: 100 * r for k in SEARCH_TIMES}})
            hot.append({"pair": pair, "variant": name, "measurement": {
                k: 100 * r for k in ("wall_ms", "cpu_ms", "p95_us", "first_pass_ms")}})
    for corpus in ("continuity", "holdout"):
        for name, live in (("baseline", 3 * 1024 * 1024), ("candidate", 1024 * 1024)):
            memories.append({"variant": name, "corpus": corpus, "measurement": memory(live)})
    return startup, readers, searches, hot, memories


def acceptance_variant(root, cache_flags=None, commands="-DORIENT_FATHOM_DIAGNOSTICS=0"):
    root = Path(root)
    paths = {}
    for name in ("engine", "reader", "search", "diagnostics", "build_cache", "compile_commands"):
        path = root / name
        path.write_text(name)
        paths[name] = path
    flags = {"CMAKE_BUILD_TYPE": "Release", "ORIENT_NATIVE": "ON", "ORIENT_FATHOM_PREFIX_LENGTH": "ON",
             "ORIENT_FATHOM_DIAGNOSTICS": "OFF", **(cache_flags or {})}
    paths["build_cache"].write_text("".join(f"{k}:STRING={v}\n" for k, v in flags.items()))
    paths["compile_commands"].write_text(json.dumps([{"command": "c++ " + commands}]))
    return {**{k: artifact(p) for k, p in paths.items()}, "profiling_enabled": False,
            "diagnostics_enabled": False, "io": "mmap"}


class ReaderMemoryGuards(unittest.TestCase):
    def test_real_cmake_comments_and_blank_lines_do_not_enter_keys(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "CMakeCache.txt"
            path.write_text("# CMake cache\n\n// Build type\nCMAKE_BUILD_TYPE:STRING=Release\n"
                            "\n// Compiler path\nCMAKE_CXX_COMPILER:FILEPATH=/with space/c++\n"
                            "\n// Native CPU\nORIENT_NATIVE:BOOL=ON\n")
            self.assertEqual(cmake_values(path), {"CMAKE_BUILD_TYPE": "Release",
                "CMAKE_CXX_COMPILER": "/with space/c++", "ORIENT_NATIVE": "ON"})

    def test_exactly_five_pairs_alternate_two_variants(self):
        self.assertEqual(alternating_orders(["baseline", "candidate"]),
                         [["baseline", "candidate"], ["candidate", "baseline"],
                          ["baseline", "candidate"], ["candidate", "baseline"], ["baseline", "candidate"]])
        for names, count in ((["a"], 5), (["a", "a"], 5), (["a", "b"], 4), (["a", "b"], 5.0)):
            with self.assertRaises(ValueError): alternating_orders(names, count)

    def test_startup_has_twenty_fresh_samples_and_uses_median(self):
        rows = [{"constructor_ms": 1., "configured_ready_ms": 2., "setup_first_root_ms": 3.,
                 "result": {"bestmove": "a1a2"}} for _ in range(20)]
        rows[-1]["constructor_ms"] = 1000.
        self.assertEqual(summarize_startup(rows)["constructor_ms"], 1.)
        self.assertIsNone(summarize_startup(rows)["cpu_ms"])
        with self.assertRaises(ValueError): summarize_startup(rows[:-1])
        rows[-1]["result"] = {"bestmove": "a1b1"}
        with self.assertRaisesRegex(ValueError, "changed results"): summarize_startup(rows)

    def test_startup_rejects_invalid_measurements(self):
        rows = [{"constructor_ms": 1., "configured_ready_ms": 2., "setup_first_root_ms": 3., "result": {}}
                for _ in range(20)]
        for value in (0, -1, True, float("nan"), float("inf")):
            changed = deepcopy(rows); changed[0]["configured_ready_ms"] = value
            with self.assertRaises(ValueError): summarize_startup(changed)

    def test_memory_requires_all_lifecycle_phases_and_explicit_teardown(self):
        validate_memory(memory(), 9985)
        for field in ("reader_requested_live_bytes", "reader_mapped_bytes"):
            bad = memory(); bad["phases"]["after_explicit_teardown"][field] = 1
            with self.assertRaisesRegex(ValueError, "teardown retained"): validate_memory(bad, 9985)
        bad = memory(); del bad["phases"]["after_adapter_destruction"]
        with self.assertRaisesRegex(ValueError, "all lifecycle"): validate_memory(bad, 9985)

    def test_memory_savings_use_reader_payload_not_rss(self):
        rows = fixtures()[-1]
        for row in rows:
            row["measurement"]["peak_rss_kib"] = 999999999 if row["variant"] == "candidate" else 1
        saving = memory_savings(rows, "baseline", "candidate")
        self.assertEqual(saving["continuity"]["after_init"], 2 * 1024 * 1024)
        rows[0]["measurement"]["semantic_hash"] = "changed"
        with self.assertRaisesRegex(ValueError, "chess results"): memory_savings(rows, "baseline", "candidate")

    def test_memory_sample_must_be_diagnostic_and_uncached(self):
        for key, value in (("diagnostics_enabled", False), ("cache_bytes", 1), ("cache_bytes", False)):
            raw = memory(); raw[key] = value
            with self.assertRaises(ValueError): validate_memory(raw, 9985)

    def test_diagnostic_catalogue_identity_matches_variant(self):
        for catalog, capacities in ((False, (650, 861)), (True, (84, 61))):
            raw = memory()
            for phase in ("after_init", "after_full_sweep"):
                raw["phases"][phase].update(reader_piece_count=84, reader_pawn_count=61,
                                           reader_piece_capacity=capacities[0], reader_pawn_capacity=capacities[1])
            validate_memory(raw, 9985, catalog)
            raw["phases"]["after_full_sweep"]["reader_piece_capacity"] = 650 if catalog else 84
            with self.assertRaisesRegex(ValueError, "counts/capacities"): validate_memory(raw, 9985, catalog)

    def test_all_adoption_gates_pass_together(self):
        result = comparison(*fixtures(), "baseline", "candidate")
        self.assertTrue(result["adopt"])
        self.assertAlmostEqual(result["time_ratios_candidate_over_baseline"]["constructor_ms"], .5)
        self.assertAlmostEqual(result["time_ratios_candidate_over_baseline"]["continuity/wdl/wall_ms"], .99)

    def test_memory_target_required_at_both_phases_and_corpora(self):
        for phase in ("after_init", "after_full_sweep"):
            rows = fixtures()
            rows[-1][-1]["measurement"]["phases"][phase]["reader_requested_live_bytes"] = 3 * 1024 * 1024
            self.assertFalse(comparison(*rows, "baseline", "candidate")["adopt"])

    def test_twenty_percent_startup_reduction_is_required(self):
        for field in ("constructor_ms", "configured_ready_ms"):
            rows = fixtures()
            for row in rows[0]:
                if row["variant"] == "candidate": row["measurement"][field] = 3.21
            self.assertFalse(comparison(*rows, "baseline", "candidate")["adopt"])

    def test_regression_over_five_percent_rejects(self):
        rows = fixtures(1.051)
        self.assertFalse(comparison(*rows, "baseline", "candidate")["adopt"])
        self.assertTrue(comparison(*fixtures(1.05), "baseline", "candidate")["adopt"])

    def test_missing_or_duplicate_pair_rejected(self):
        for duplicate in (False, True):
            rows = fixtures()
            if duplicate: rows[1].append(rows[1][0])
            else: rows[1].pop()
            with self.assertRaisesRegex(ValueError, "paired sample"): comparison(*rows, "baseline", "candidate")

    def test_search_rejects_wrong_work_or_cache(self):
        validate_search(search(), 9985, 3, 4)
        for key, value in (("search_positions", 47), ("positions", 9984), ("root_positions", 1),
                           ("depth", 5), ("repeats", 2), ("cache_bytes", 1), ("profiling_enabled", True)):
            raw = search(); raw[key] = value
            with self.assertRaises(ValueError): validate_search(raw, 9985, 3, 4)

    def test_search_hashes_and_latency_order_required(self):
        for key in SEARCH_HASHES:
            raw = search(); raw[key] = ""
            with self.assertRaises(ValueError): validate_search(raw, 9985, 3, 4)
        raw = search(); raw["root_latency_median_us"] = 101
        with self.assertRaises(ValueError): validate_search(raw, 9985, 3, 4)

    def test_disabled_acceptance_build_passes(self):
        with tempfile.TemporaryDirectory() as root: verify_variant(acceptance_variant(root))

    def test_instrumentation_and_rejected_experiments_are_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            for flag in ("ORIENT_FATHOM_DIAGNOSTICS", "ORIENT_TABLEBASE_PROFILING", "ORIENT_FATHOM_PROFILE",
                         "ORIENT_COMPACT_TABLEBASE_CACHE", "ORIENT_REUSE_ROOT_LEGAL"):
                with self.subTest(flag=flag):
                    with self.assertRaises(ValueError): verify_variant(acceptance_variant(root, {flag: "ON"}))
                    with self.assertRaises(ValueError): verify_variant(acceptance_variant(root, commands="-D" + flag + "=1"))

    def test_artifact_change_is_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            row = acceptance_variant(root)
            Path(row["engine"]["path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"): verify_variant(row)

    def test_actual_library_and_dtz_shim_definitions_must_match(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "commands"
            records = [{"file": name, "command": "c++ -DORIENT_FATHOM_FIVE_PIECE_CATALOG=1 -DORIENT_FATHOM_DIAGNOSTICS=0"}
                       for name in ("tbprobe.c", "reader_compare_dtz.cpp")]
            path.write_text(json.dumps(records)); verify_catalog_commands(path, True)
            records[1]["command"] = "c++ -DORIENT_FATHOM_FIVE_PIECE_CATALOG=0"
            path.write_text(json.dumps(records))
            with self.assertRaisesRegex(ValueError, "inconsistent"): verify_catalog_commands(path, True)
            path.write_text(json.dumps(records[:1]))
            with self.assertRaisesRegex(ValueError, "missing"): verify_catalog_commands(path, True)

    def test_baseline_absent_catalogue_option_means_full_catalogue(self):
        with tempfile.TemporaryDirectory() as root:
            row = acceptance_variant(root)
            path = Path(row["compile_commands"]["path"])
            path.write_text(json.dumps([{"file": name, "command": "c++"}
                                        for name in ("tbprobe.c", "reader_compare_dtz.cpp")]))
            row["compile_commands"] = artifact(path)
            verify_variant(row, catalog=False)
            with self.assertRaisesRegex(ValueError, "catalogue build setting"): verify_variant(row, catalog=True)

    def test_separate_diagnostic_build_is_pinned_and_matches_settings(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            row = acceptance_variant(root)
            commands = Path(row["compile_commands"]["path"])
            commands.write_text(json.dumps([{"file": name, "command": "c++ -DORIENT_FATHOM_DIAGNOSTICS=0"}
                                            for name in ("tbprobe.c", "reader_compare_dtz.cpp")]))
            row["compile_commands"] = artifact(commands)
            diag_cache, diag_commands = root / "diag-cache", root / "diag-commands"
            diag_cache.write_text(Path(row["build_cache"]["path"]).read_text().replace(
                "ORIENT_FATHOM_DIAGNOSTICS:STRING=OFF", "ORIENT_FATHOM_DIAGNOSTICS:STRING=ON"))
            diag_commands.write_text(json.dumps([{"file": name, "command": "c++ -DORIENT_FATHOM_DIAGNOSTICS=1"}
                                                 for name in ("tbprobe.c", "benchmark_reader_memory.cpp")]))
            row.update(diag_build_cache=artifact(diag_cache), diag_compile_commands=artifact(diag_commands))
            verify_variant(row, catalog=False)
            diag_cache.write_text(diag_cache.read_text().replace("ORIENT_NATIVE:STRING=ON", "ORIENT_NATIVE:STRING=OFF"))
            row["diag_build_cache"] = artifact(diag_cache)
            with self.assertRaisesRegex(ValueError, "compiler/settings differ"): verify_variant(row, catalog=False)

    def test_commands_preserve_spaces_and_pinned_binary(self):
        variant = {"reader": {"path": "/with space/reader"}}
        config = {"depth": 4, "search_fixture": {"file": {"path": "/search48"}},
                  "hot_fixture": {"file": {"path": "/hot145"}}}
        cmd = command_for(variant, "reader", "/tables with space", {"file": {"path": "/corpus"}}, "wdl", 20, config)
        self.assertEqual(cmd, ["/with space/reader", "/tables with space", "/corpus", "wdl", "20", "mmap"])
        variant["reader_argv_template"] = ["unbound", "{tables}"]
        with self.assertRaises(ValueError): command_for(variant, "reader", "/tables", {"file": {"path": "/c"}}, "wdl", 20, config)

    def test_fixture_count_and_complete_fen_are_required(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "fixture"
            path.write_text("4k3/8/8/8/8/8/8/K2Q4 w - - 0 1\n")
            self.assertEqual(len(check_fixture({"file": artifact(path), "positions": 1}, 1)), 1)
            path.write_text("4k3/8/8/8/8/8/8/K2Q4 w - -\n")
            with self.assertRaisesRegex(ValueError, "six FEN"): check_fixture({"file": artifact(path), "positions": 1}, 1)

    def test_startup_transport_records_exact_result_and_raw_output(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            engine = root / "fake-engine"
            engine.write_text("#!/usr/bin/env python3\n" + '''import sys
for line in sys.stdin:
    command = line.strip()
    if command == "uci":
        print("uciok", flush=True)
    elif command == "isready":
        print("readyok", flush=True)
    elif command.startswith("go "):
        print("info depth 0 score cp 25000 nodes 0 tbhits 1 time 0 pv a1a2", flush=True)
        print("bestmove a1a2", flush=True)
    elif command == "quit":
        break
''')
            engine.chmod(0o700)
            output, errors = root / "stdout", root / "stderr"
            result = startup_uci(str(engine), "/tables with space", "4k3/8/8/8/8/8/8/K2Q4 w - - 0 1",
                                 {"Hash": 16, "Threads": 1}, output, errors)
            self.assertEqual(result["result"], {"bestmove": "a1a2", "score_kind": "cp", "score": 25000,
                                                "nodes": 0, "tbhits": 1})
            self.assertGreater(result["setup_first_root_ms"], result["configured_ready_ms"])
            self.assertIsNone(result["cpu_ms"])
            self.assertIn("bestmove a1a2", output.read_text())
            self.assertEqual(errors.read_text(), "")

    def test_proof_requires_native_ordered_result_and_engine_bindings(self):
        with tempfile.TemporaryDirectory() as root:
            paths = {}
            for name in ("reader", "engine", "search", "continuity", "holdout", "dataset", "other"):
                path = Path(root) / name; path.write_text(name); paths[name] = artifact(path)
            config = {"variants": {"baseline": {k: paths[k] for k in ("reader", "engine", "search")}},
                      "corpora": {n: {"file": paths[n], "positions": 1} for n in ("continuity", "holdout")},
                      "tablebase_manifest": paths["dataset"]}
            proof = {"status": "passed", "all_semantic_results_equal": True,
                     "exact_ordered_results_equal": True, "variant_names": ["baseline"],
                     "operations": ["wdl", "dtz", "all_moves"], "binaries": {"baseline": paths["reader"]},
                     "engine_binaries": {"baseline": paths["engine"]}, "search_binaries": {"baseline": paths["search"]},
                     "corpora": config["corpora"], "tablebase_manifest": paths["dataset"]}
            validate_proof(proof, config)
            bad = deepcopy(proof); bad["exact_ordered_results_equal"] = False
            with self.assertRaisesRegex(ValueError, "ordered alternatives"): validate_proof(bad, config)
            bad = deepcopy(proof); bad["engine_binaries"]["baseline"] = paths["other"]
            with self.assertRaisesRegex(ValueError, "engine_binaries"): validate_proof(bad, config)


if __name__ == "__main__": unittest.main()
