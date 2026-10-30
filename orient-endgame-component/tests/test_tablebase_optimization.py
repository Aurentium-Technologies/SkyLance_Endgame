"""Network-free regression checks for the declared optimization adoption gates."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from measure_tablebase_optimization import comparison, decisions, geomean


PAIR_SCALES = (0.93, 0.98, 1.02, 1.06, 1.01)
CASES = ([("baseline", cache) for cache in (0, 1, 4, 16)] + [("root-only", 0)]
         + [("compact-only", cache) for cache in (0, 1, 4, 16)]
         + [("combined", cache) for cache in (0, 1, 4, 16)])


def trials():
    """Five correlated pairs of all thirteen configurations, with modest drift."""
    rows = []
    for pair, scale in enumerate(PAIR_SCALES, 1):
        for family, cache in CASES:
            search = {0: 100.0, 1: 98.0, 4: 97.0, 16: 102.0}[cache]
            faster_root = family in ("root-only", "combined")
            rows.append({"pair": pair, "case": f"{family}-{cache}",
                         "search_ms": search * scale,
                         "root_ms": (90.0 if faster_root else 100.0) * scale,
                         "root_latency_p95_us": (9.4 if faster_root else 10.0) * scale,
                         "distinct_lookup_ms": 100.0 * scale})
    return rows


def change(rows, case, **measurements):
    for row in rows:
        if row["case"] == case:
            for field, value in measurements.items():
                row[field] = value * PAIR_SCALES[row["pair"] - 1]


class AdoptionTests(unittest.TestCase):
    def test_comparison_uses_paired_time_ratios(self):
        rows = trials()
        result = comparison(rows, "root-only-0", "baseline-0")
        self.assertAlmostEqual(result["root_speedup"], 100.0 / 90.0)
        self.assertAlmostEqual(result["root_time_ratio"], 0.9)
        self.assertAlmostEqual(result["root_p95_ratio"], 0.94)
        self.assertAlmostEqual(result["search_time_ratio"], 1.0)

    def test_faster_root_rejected_when_p95_regresses(self):
        rows = trials()
        change(rows, "root-only-0", root_ms=70.0, root_latency_p95_us=10.51)
        result = decisions(rows)
        self.assertGreater(result["root_only"]["root_speedup"], 1.05)
        self.assertGreater(result["root_only"]["root_p95_ratio"], 1.05)
        self.assertFalse(result["root_only"]["passes"])
        self.assertEqual(result["recommended_family"], "compact-only")

    def test_raw_lookup_improvement_without_search_gain_keeps_default_zero(self):
        rows = trials()
        for cache in (1, 4, 16):
            change(rows, f"combined-{cache}", distinct_lookup_ms=20.0)
        result = decisions(rows)
        self.assertEqual(result["recommended_family"], "combined")
        self.assertTrue(result["compact_passes_all_matched_memory"])
        self.assertEqual(result["recommended_cache_mib"], 0)
        self.assertTrue(all(item["distinct_time_ratio"] < 0.25
                            for item in result["nonzero_default_candidates"]))
        self.assertTrue(all(not item["passes"] for item in result["nonzero_default_candidates"]))

    def test_every_compact_matched_memory_setting_must_pass(self):
        for failing_cache in (1, 4, 16):
            with self.subTest(cache=failing_cache):
                rows = trials()
                change(rows, f"compact-only-{failing_cache}", search_ms=120.0)
                result = decisions(rows)
                self.assertFalse(result["compact_passes_all_matched_memory"])
                self.assertEqual(sum(not item["passes"] for item in result["compact_matched_memory"]), 1)
                self.assertEqual(result["recommended_family"], "root-only")
                self.assertEqual(result["recommended_cache_mib"], 0)
                self.assertEqual(result["nonzero_default_candidates"], [])

    def test_combination_interference_prefers_independent_root_change(self):
        rows = trials()
        change(rows, "combined-0", root_ms=99.0)
        result = decisions(rows)
        self.assertTrue(result["root_only"]["passes"])
        self.assertTrue(result["compact_passes_all_matched_memory"])
        self.assertFalse(result["combined_zero_cache"]["passes_root_gate"])
        self.assertEqual(result["recommended_family"], "root-only")
        self.assertEqual(result["recommended_cache_mib"], 0)

    def test_smallest_passing_cache_is_selected(self):
        for selected in (1, 4, 16):
            with self.subTest(selected=selected):
                rows = trials()
                for cache in (1, 4, 16):
                    # Every cache speeds complete searches enough. Smaller
                    # settings are independently rejected by lookup regression.
                    change(rows, f"combined-{cache}", search_ms=90.0,
                           distinct_lookup_ms=110.0 if cache < selected else 100.0)
                result = decisions(rows)
                self.assertEqual(result["recommended_family"], "combined")
                self.assertEqual(result["recommended_cache_mib"], selected)

    def test_root_regression_blocks_nonzero_default_despite_search_gain(self):
        rows = trials()
        for cache in (1, 4, 16):
            change(rows, f"combined-{cache}", search_ms=80.0, root_ms=110.0)
        result = decisions(rows)
        self.assertEqual(result["recommended_cache_mib"], 0)
        self.assertTrue(all(item["search_speedup"] > 1.05
                            for item in result["nonzero_default_candidates"]))
        self.assertTrue(all(not item["passes"] for item in result["nonzero_default_candidates"]))

    def test_no_independent_change_passing_preserves_baseline(self):
        rows = trials()
        change(rows, "root-only-0", root_ms=100.0)
        change(rows, "compact-only-4", search_ms=120.0)
        result = decisions(rows)
        self.assertEqual(result["recommended_family"], "baseline")
        self.assertEqual(result["recommended_cache_mib"], 0)

    def test_geomean_rejects_invalid_measurements(self):
        for values in ([], [0], [-1], [float("inf")], [float("nan")]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    geomean(values)


if __name__ == "__main__":
    unittest.main()
