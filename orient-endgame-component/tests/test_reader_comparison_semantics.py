"""Lock the frozen verifier's explicit normalization and rejection contract.

This does not claim canonical() rejects every malformed top-level field. A
separate typed-value audit validates the actual recorded reader outputs.
"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from experiment import artifact
from verify_reader_comparison import canonical, load_corpora, validate_output_rows


def row(**changes):
    return {"parse_ok": True, "status": 0, "wdl": 4, "dtz_status": 0,
            "signed_dtz": 7, "nominal_wdl": 4, "dtz": 7, "root_status": 0,
            "root_wdl": 4, "root_dtz": 7, "suggested": "a1a2",
            "dtz_rounded": False, "root_rounded": False,
            "moves": [["a1a2", 4, 7], ["a1b1", 2, 0]], **changes}


class CanonicalReaderSemantics(unittest.TestCase):
    def test_rounding_annotations_and_legal_tie_choice_are_diagnostics(self):
        baseline = row(moves=[["a1a2", 4, 7], ["a1b1", 4, 7]])
        other = deepcopy(baseline)
        other.update(suggested="a1b1", dtz_rounded=True, root_rounded=True,
                     move_rounding=[["a1a2", True], ["a1b1", True]])
        self.assertEqual(canonical(baseline), canonical(other))

    def test_signed_dtz_is_exact_not_plus_or_minus_one(self):
        for delta in (-7, 6, 8):
            with self.subTest(dtz=delta):
                self.assertNotEqual(canonical(row()), canonical(row(signed_dtz=delta)))

    def test_all_successful_semantic_fields_affect_comparison(self):
        for field, value in (("parse_ok", False), ("wdl", 3), ("nominal_wdl", 3),
                             ("dtz", 8), ("root_wdl", 3), ("root_dtz", 8)):
            with self.subTest(field=field):
                self.assertNotEqual(canonical(row()), canonical(row(**{field: value})))

    def test_full_move_values_and_legal_set_are_compared(self):
        for alternatives in ([["a1a2", 3, 7], ["a1b1", 2, 0]],
                             [["a1a2", 4, 8], ["a1b1", 2, 0]],
                             [["a1a2", 4, 7]]):
            with self.subTest(moves=alternatives):
                self.assertNotEqual(canonical(row()), canonical(row(moves=alternatives)))

    def test_unknown_status_is_rejected(self):
        for field in ("status", "dtz_status", "root_status"):
            for value in (-1, 3, "success"):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "invalid probe status"):
                    canonical(row(**{field: value}))

    def test_duplicate_and_noncanonical_order_are_rejected(self):
        for alternatives in ([["a1a2", 4, 7], ["a1a2", 2, 0]],
                             [["a1b1", 2, 0], ["a1a2", 4, 7]]):
            with self.subTest(moves=alternatives), self.assertRaisesRegex(ValueError, "duplicate or noncanonical"):
                canonical(row(moves=alternatives))

    def test_invalid_move_outcome_or_negative_distance_is_rejected(self):
        for value, distance in ((-1, 7), (5, 7), (2.5, 7), (4, -1)):
            with self.subTest(wdl=value, dtz=distance), self.assertRaisesRegex(ValueError, "invalid move value"):
                canonical(row(moves=[["a1a2", value, distance]]))

    def test_recommendation_must_be_a_returned_legal_alternative(self):
        with self.assertRaisesRegex(ValueError, "illegal reader recommendation"):
            canonical(row(suggested="h8h7"))

    def test_terminal_no_move_sentinel_is_accepted(self):
        self.assertEqual(canonical(row(suggested="0000", moves=[])),
                         canonical(row(suggested="0000", moves=[], dtz_rounded=True)))

    def test_failed_probe_placeholder_values_are_not_compared(self):
        baseline = row(status=1, dtz_status=2, root_status=1, suggested="0000", moves=[])
        other = {**baseline, "wdl": 0, "signed_dtz": -99, "nominal_wdl": 0,
                 "dtz": 99, "root_wdl": 0, "root_dtz": 99}
        self.assertEqual(canonical(baseline), canonical(other))
        self.assertNotEqual(canonical(baseline), canonical({**other, "dtz_status": 1}))


class CorrectnessInputBindings(unittest.TestCase):
    FEN = "4k3/8/8/8/8/8/8/4K2R w - - 0 1"

    def config(self, root):
        binary, dataset, corpus = (root / name for name in ("reader", "manifest", "corpus.fen"))
        binary.write_text("reader fixture")
        dataset.write_text("dataset fixture")
        corpus.write_text(self.FEN + "\n")
        return {"variants": {name: {"binary": artifact(binary), "io": "mmap"}
                             for name in ("baseline", "candidate")},
                "tablebase_manifest": artifact(dataset),
                "corpora": {"holdout": {"file": artifact(corpus), "positions": 1}}}

    def test_reject_empty_comparisons_and_single_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(Path(tmp))
            self.assertEqual(load_corpora(config), {"holdout": [self.FEN]})
            for changes in ({"variants": {}}, {"variants": {"only": config["variants"]["baseline"]}},
                            {"corpora": {}}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    load_corpora({**config, **changes})

    def test_bind_actual_corpus_contents_and_pinned_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(Path(tmp))
            for count in (0, True, 2):
                config["corpora"]["holdout"]["positions"] = count
                with self.subTest(count=count), self.assertRaises(ValueError):
                    load_corpora(config)
            config["corpora"]["holdout"]["positions"] = 1
            Path(config["tablebase_manifest"]["path"]).write_text("changed dataset")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                load_corpora(config)

    def test_all_readers_returning_the_same_wrong_fen_is_rejected(self):
        correct = row(line=1, fen=self.FEN)
        self.assertEqual(validate_output_rows([correct], [self.FEN]), [correct])
        wrong = row(line=1, fen="4k3/8/8/8/8/8/8/R3K3 b - - 0 1")
        with self.assertRaisesRegex(ValueError, "pinned fixture order"):
            validate_output_rows([wrong], [self.FEN])
        for changes in ({"line": True}, {"line": 2}, {"parse_ok": "true"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_output_rows([{**correct, **changes}], [self.FEN])


if __name__ == "__main__": unittest.main()
