"""Lightweight exact-result/provenance guards; no engine or tablebase probes."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from experiment import artifact
from verify_reader_memory import (load_corpora, read_rows, require_native_order, row_differences,
                                  strict_json, validate_row, verify_artifacts)


FEN = "4k3/8/8/8/8/8/8/R3K3 w - - 0 1"
OTHER = "4k3/8/8/8/8/8/8/R3K3 b - - 0 1"


def native():
    return {"status": 0, "wdl": 4, "root_status": 0, "root_wdl": 4, "dtz": 5,
            "suggested": "a1a2", "moves": [["a1a3", 4, 9], ["a1a2", 4, 7]]}


def reader():
    value = native()
    value.update(line=1, fen=FEN, parse_ok=True, parse_error="", dtz_status=0,
                 signed_dtz=5, nominal_wdl=4, root_dtz=5, dtz_rounded=None)
    value["moves"] = sorted(value["moves"])
    return value


class ReaderMemoryVerification(unittest.TestCase):
    def test_native_order_is_retained_and_compared(self):
        value = native()
        self.assertEqual(validate_row(value, "native", 1, FEN, True), value)
        changed = deepcopy(value); changed["moves"].reverse()
        found = row_differences([value], [changed])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["reference"]["moves"][0][0], "a1a3")

    def test_sorted_native_build_cannot_claim_reader_order_coverage(self):
        require_native_order([native()])
        sorted_row = native(); sorted_row["moves"].sort()
        with self.assertRaisesRegex(ValueError, "appears to sort"):
            require_native_order([sorted_row])

    def test_recommendations_and_dtz_are_not_ignored(self):
        value = native()
        for changes in ({"dtz": 6}, {"suggested": "a1a3"}):
            changed = dict(value, **changes)
            validate_row(changed, "native", 1, FEN)
            self.assertEqual(len(row_differences([value], [changed])), 1)

    def test_boolean_and_float_numeric_payloads_rejected(self):
        for changes in ({"status": False}, {"wdl": 4.0}, {"dtz": True},
                        {"root_status": 3}, {"root_wdl": 99}, {"dtz": -1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_row(dict(native(), **changes), "native", 1, FEN)

    def test_duplicate_or_malformed_alternatives_rejected(self):
        for moves in ([["a1a2", 4, 1], ["a1a2", 4, 2]], [["a1z9", 4, 1]],
                      [["a1a2", True, 1]], [["a1a2", 4, -1]], [["a1a2", 4]]):
            with self.subTest(moves=moves), self.assertRaises(ValueError):
                validate_row(dict(native(), moves=moves), "native", 1, FEN)

    def test_recommendation_must_be_in_alternatives(self):
        with self.assertRaisesRegex(ValueError, "recommendation missing"):
            validate_row(dict(native(), suggested="a1a4"), "native", 1, FEN)

    def test_raw_reader_requires_exact_schema_and_fixture_alignment(self):
        validate_row(reader(), "reader", 1, FEN, True)
        for changes in ({"line": 2}, {"fen": OTHER}, {"parse_ok": 1},
                        {"parse_error": "warning"}, {"dtz_rounded": False},
                        {"signed_dtz": -6}, {"nominal_wdl": 99}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_row(dict(reader(), **changes), "reader", 1, FEN)
        with self.assertRaisesRegex(ValueError, "output fields"):
            validate_row(dict(reader(), unexpected=0), "reader", 1, FEN)

    def test_raw_reader_canonical_order_is_required(self):
        value = reader(); value["moves"].reverse()
        with self.assertRaisesRegex(ValueError, "canonical UCI order"):
            validate_row(value, "reader", 1, FEN)

    def test_failure_payloads_cannot_masquerade_as_success(self):
        failure = {"status": 1, "wdl": 2, "root_status": 1, "root_wdl": 2,
                   "dtz": 0, "suggested": "0000", "moves": []}
        validate_row(failure, "native", 1, FEN)
        with self.assertRaisesRegex(ValueError, "covered material"):
            validate_row(failure, "native", 1, FEN, True)
        with self.assertRaisesRegex(ValueError, "successful payload"):
            validate_row(dict(failure, moves=[["a1a2", 4, 1]]), "native", 1, FEN)
        mate = dict(failure, status=0, wdl=0, root_status=0, root_wdl=0)
        validate_row(mate, "native", 1, FEN)
        with self.assertRaisesRegex(ValueError, "terminal payload"):
            validate_row(dict(mate, dtz=1), "native", 1, FEN)

    def test_json_duplicate_keys_and_nonfinite_constants_are_rejected(self):
        for text in ('{"status":0,"status":1}', '{"wdl":NaN}', '{"dtz":Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError): strict_json(text)

    def test_missing_extra_blank_or_invalid_json_rows_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output.jsonl"
            text = json.dumps(native())
            path.write_text(text + "\n")
            self.assertEqual(len(read_rows(path, "native", [FEN], True)), 1)
            for output in ("", text + "\n" + text + "\n", "\n", "not JSON\n"):
                path.write_text(output)
                with self.subTest(output=output), self.assertRaises(ValueError):
                    read_rows(path, "native", [FEN], True)

    def test_corpus_hash_count_fen_fields_and_disjointness_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = (Path(tmp) / name for name in ("a.fen", "b.fen"))
            a.write_text(FEN + "\n"); b.write_text(OTHER + "\n")
            rows = {"continuity": {"file": artifact(a), "positions": 1},
                    "holdout": {"file": artifact(b), "positions": 1}}
            expected = {"continuity": 1, "holdout": 1}
            self.assertEqual(load_corpora(rows, expected)["continuity"], [FEN])
            b.write_text(FEN + "\n"); rows["holdout"]["file"] = artifact(b)
            with self.assertRaisesRegex(ValueError, "overlaps"): load_corpora(rows, expected)
            b.write_text(" ".join(OTHER.split()[:4]) + "\n"); rows["holdout"]["file"] = artifact(b)
            with self.assertRaisesRegex(ValueError, "complete FEN"): load_corpora(rows, expected)
            rows["holdout"]["positions"] = True
            with self.assertRaisesRegex(ValueError, "position count"): load_corpora(rows, expected)

    def test_recursive_artifact_drift_and_comparison_row_count_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "binary"; path.write_bytes(b"frozen")
            config = {"variants": {"baseline": {"reader": artifact(path)}}}
            verify_artifacts(config)
            path.write_bytes(b"changed")
            with self.assertRaises(ValueError): verify_artifacts(config)
        with self.assertRaisesRegex(ValueError, "row counts"):
            row_differences([native()], [])


if __name__ == "__main__": unittest.main()
