"""External-reader timing/provenance guards; never invokes a reader binary."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from experiment import artifact
from measure_reader_comparison import (command_for, geomean, paired_comparison,
                                       operation_repeats, rotated_orders, validate_correctness, validate_sample,
                                       verify_artifacts, verify_corpora)


def sample(**changes):
    return {"mode": "wdl", "positions": 4, "repeats": 3, "calls": 12,
            "semantic_hash": "exact-answers", "profiling_enabled": False, "backend": "mmap",
            "wall_ms": 10., "cpu_ms": 9., "p50_us": 1., "p95_us": 3.,
            "startup_ms": 1., "first_pass_ms": 2., "first_pass_cpu_ms": 1.,
            "peak_rss_kib": 2048, **changes}


def trials():
    rows = []
    for i in range(1, 6):
        for name, ratio in (("orient", 1.), ("rust", .75)):
            data = sample()
            for field in ("wall_ms", "cpu_ms", "p50_us", "p95_us", "startup_ms", "first_pass_ms", "peak_rss_kib"):
                data[field] *= ratio * (1 + i / 10)
            rows.append({"pair": i, "variant": name, "corpus": "holdout",
                         "operation": "wdl", "measurement": data})
    return rows


class ReaderComparisonGuards(unittest.TestCase):
    def test_order_rotates_every_reader_without_dropping_cases(self):
        orders = rotated_orders(["orient", "mmap", "pread"])
        self.assertEqual(len(orders), 5)
        self.assertEqual(orders[:3], [["orient", "mmap", "pread"], ["mmap", "pread", "orient"], ["pread", "orient", "mmap"]])

    def test_order_rejects_duplicate_or_single_reader(self):
        for names in (["only"], ["a", "a"]):
            with self.assertRaises(ValueError): rotated_orders(names)

    def test_sample_requires_equal_requested_work(self):
        self.assertEqual(validate_sample(sample(), "wdl", 4, 3)["calls"], 12)
        for delta in ({"positions": 3}, {"calls": 11}, {"mode": "dtz"}, {"profiling_enabled": True}):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                validate_sample(sample(**delta), "wdl", 4, 3)

    def test_invalid_metrics_and_quantile_order_rejected(self):
        for delta in ({"wall_ms": 0}, {"cpu_ms": math.inf}, {"p50_us": 4},
                      {"p95_us": float("nan")}, {"peak_rss_kib": -1}, {"semantic_hash": ""}):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                validate_sample(sample(**delta), "wdl", 4, 3)

    def test_operation_specific_repeat_counts_and_fallback(self):
        config = {"repeats": 3, "repeats_by_operation": {"wdl": 20, "dtz": 10}}
        self.assertEqual([operation_repeats(config, op) for op in ("wdl", "dtz", "all_moves")], [20, 10, 3])
        self.assertEqual(operation_repeats({"repeats": 7}, "wdl"), 7)
        for op, count in (("wdl", 20), ("dtz", 10), ("all_moves", 3)):
            validate_sample(sample(mode=op, repeats=count, calls=4 * count), op, 4, count, "mmap")
            with self.assertRaisesRegex(ValueError, "operation count"):
                validate_sample(sample(mode=op, repeats=count, calls=4 * count - 1), op, 4, count, "mmap")

    def test_invalid_repeat_configuration_is_rejected(self):
        for config in ({"repeats": True}, {"repeats": 0}, {"repeats_by_operation": {"unknown": 3}},
                       {"repeats_by_operation": {"wdl": 101}}, {"repeats_by_operation": {"wdl": False}}):
            with self.subTest(config=config), self.assertRaises(ValueError): operation_repeats(config, "wdl")

    def test_backend_and_result_cache_are_explicit(self):
        validate_sample(sample(backend="pread"), "wdl", 4, 3, "pread")
        for delta in ({"backend": "pread"}, {"backend": None}, {"cache_bytes": 1}, {"cache_bytes": False}):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                validate_sample(sample(**delta), "wdl", 4, 3, "mmap")
        validate_sample(sample(cache_bytes=0), "wdl", 4, 3, "mmap")

    def test_paired_ratio_direction_and_time_saved(self):
        row = paired_comparison(trials(), "orient", "rust", "holdout", "wdl")
        self.assertAlmostEqual(row["wall_ms_ratio"], .75)
        self.assertAlmostEqual(row["throughput_ratio"], 4 / 3)
        self.assertAlmostEqual(row["wall_time_reduction_percent"], 25)

    def test_missing_or_duplicate_pair_rejected(self):
        for rows in (trials()[:-1], trials() + trials()[:1]):
            with self.assertRaises(ValueError): paired_comparison(rows, "orient", "rust", "holdout", "wdl")

    def test_zero_tiny_resource_counter_is_unavailable_ratio(self):
        rows = trials()
        for row in rows: row["measurement"]["startup_ms"] = 0
        self.assertIsNone(paired_comparison(rows, "orient", "rust", "holdout", "wdl")["startup_ms_ratio"])

    def test_hash_verification_detects_nested_artifact_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "binary"; p.write_bytes(b"pinned")
            config = {"variants": [{"build": {"binary": artifact(p)}}]}
            verify_artifacts(config)
            p.write_bytes(b"changed")
            with self.assertRaises(ValueError): verify_artifacts(config)

    def test_holdout_must_be_disjoint_and_complete_fen(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = (Path(tmp) / n for n in ("a.fen", "b.fen"))
            a.write_text("4k3/8/8/8/8/8/8/4K2R w - - 0 1\n")
            b.write_text("4k3/8/8/8/8/8/8/R3K3 b - - 0 1\n")
            rows = {"continuity": {"file": artifact(a), "positions": 1},
                    "holdout": {"file": artifact(b), "positions": 1}}
            verify_corpora(rows)
            b.write_text(a.read_text()); rows["holdout"]["file"] = artifact(b)
            with self.assertRaisesRegex(ValueError, "overlaps"): verify_corpora(rows)

    def test_empty_timing_corpora_cannot_pass_the_workload_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.fen"
            path.write_text("")
            rows = {name: {"file": artifact(path), "positions": 0}
                    for name in ("continuity", "holdout")}
            with self.assertRaisesRegex(ValueError, "positive position count"):
                verify_corpora(rows)

    def test_argv_template_keeps_spaces_as_single_arguments(self):
        row = {"binary": {"path": "/a dir/reader"}, "argv_template": ["{binary}", "{tables}", "{corpus}", "{mode}", "{repeats}"]}
        cmd = command_for(row, "/table path", {"file": {"path": "/positions path"}}, "dtz", 3)
        self.assertEqual(cmd, ["/a dir/reader", "/table path", "/positions path", "dtz", "3"])

    def test_geomean_rejects_invalid_data(self):
        for values in ([], [0], [-1], [math.inf], [math.nan]):
            with self.assertRaises(ValueError): geomean(values)

    def test_correctness_binds_current_binaries_corpora_and_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for name in ("binary", "continuity", "holdout", "dataset", "other"):
                p = Path(tmp) / name; p.write_text(name); paths[name] = artifact(p)
            config = {"variants": {"orient": {"binary": paths["binary"]}},
                      "corpora": {n: {"file": paths[n], "positions": 1} for n in ("continuity", "holdout")},
                      "tablebase_manifest": paths["dataset"]}
            def proof():
                return {"status": "passed", "all_semantic_results_equal": True,
                        "variant_names": ["orient", "extra_oracle"], "operations": ["wdl", "dtz", "all_moves"],
                        "binaries": {"orient": paths["binary"]},
                        "corpora": {**config["corpora"], "special": {"file": paths["other"], "positions": 1}},
                        "tablebase_manifest": paths["dataset"]}
            validate_correctness(proof(), config)
            bad = proof(); bad["binaries"]["orient"] = paths["other"]
            with self.assertRaisesRegex(ValueError, "stale correctness binding: binary"):
                validate_correctness(bad, config)
            bad = proof(); bad["corpora"]["holdout"] = {"file": paths["other"], "positions": 1}
            with self.assertRaisesRegex(ValueError, "stale correctness binding: corpus"):
                validate_correctness(bad, config)
            bad = proof(); bad["tablebase_manifest"] = paths["other"]
            with self.assertRaisesRegex(ValueError, "stale correctness binding: dataset"):
                validate_correctness(bad, config)
            bad = proof(); bad["corpora"]["holdout"] = {"file": paths["holdout"], "positions": 2}
            with self.assertRaisesRegex(ValueError, "corpus count"):
                validate_correctness(bad, config)


if __name__ == "__main__": unittest.main()
