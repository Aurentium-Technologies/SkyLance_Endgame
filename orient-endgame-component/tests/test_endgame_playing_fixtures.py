#!/usr/bin/env python3
"""Fixture-construction rules and prepared-set invariants; no games or network."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import prepare_endgame_playing as fixtures


class FixtureRules(unittest.TestCase):
    def test_board_round_trip_and_piece_count(self):
        fen = "5r2/8/8/8/1R6/2k5/6P1/Kq6 w - - 0 1"
        board = fixtures.board_of(fen)
        self.assertEqual(len(board), 6)
        self.assertEqual(fixtures.placement(board), fen.split()[0])
        self.assertEqual(fixtures.material(fen), "KRPvKQR")

    def test_reflection_is_involution_and_keeps_counters(self):
        fen = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 98 50"
        mirror = fixtures.reflected(fen)
        self.assertEqual(fixtures.reflected(mirror), fen)
        self.assertEqual(mirror.split()[1:], ["b", "-", "d3", "98", "50"])
        with self.assertRaises(ValueError):
            fixtures.reflected("4k3/8/8/8/8/8/8/4K2R w K - 0 1")

    def test_quiet_filter_handles_all_attack_shapes_and_blocking(self):
        self.assertTrue(fixtures.in_check("5r2/8/8/8/1R6/2k5/6P1/Kq6 w - - 0 1"))
        self.assertTrue(fixtures.in_check("4k3/8/8/8/8/8/2n5/4K3 w - - 0 1"))
        self.assertTrue(fixtures.in_check("4k3/8/8/8/8/8/3p4/4K3 w - - 0 1"))
        self.assertTrue(fixtures.in_check("4k3/8/8/8/7b/8/8/4K3 w - - 0 1"))
        self.assertFalse(fixtures.in_check("4k3/8/8/8/7b/6P1/8/4K3 w - - 0 1"))

    def test_rule_fifty_outcomes_are_not_mislabeled_as_wins(self):
        white = "4k3/8/8/8/8/8/8/4K2R w - - 0 1"
        black = fixtures.reflected(white)
        for wdl in (1, 2, 3):
            self.assertEqual(fixtures.outcome_value(wdl), 0)
            self.assertEqual(fixtures.absolute_outcome(white, wdl), "draw")
        self.assertEqual(fixtures.absolute_outcome(white, 4), "white_win")
        self.assertEqual(fixtures.absolute_outcome(white, 0), "black_win")
        self.assertEqual(fixtures.absolute_outcome(black, 4), "black_win")
        with self.assertRaises(ValueError):
            fixtures.outcome_value(5)

    def test_boundary_filter_distinguishes_quiet_and_zeroing(self):
        fen = "4k3/8/8/8/8/8/P7/4K2R w - - 98 50"
        self.assertTrue(fixtures.ambiguous_boundary(fen, {"moves": [["h1h2", 4, 2]]}))
        self.assertFalse(fixtures.ambiguous_boundary(fen, {"moves": [["a2a3", 4, 2]]}))
        self.assertFalse(fixtures.ambiguous_boundary(fen, {"moves": [["h1h2", 4, 4]]}))

    def test_full_fen_book_preserves_rule_counters(self):
        fen = "4k3/8/8/8/8/8/8/4K2R w - - 99 51"
        text = fixtures.make_book([{"id": "counter-99", "fen": fen}])
        self.assertIn('[SetUp "1"]', text)
        self.assertIn('[FEN "' + fen + '"]', text)
        self.assertIn('[CaseId "counter-99"]', text)
        self.assertTrue(text.endswith("*\n"))

    def test_missing_oracle_rows_or_outcomes_fail(self):
        class Run:
            stdout = ""
        with patch.object(fixtures.subprocess, "run", return_value=Run()):
            with self.assertRaisesRegex(ValueError, "result count"):
                fixtures.oracle_rows("unused", "unused", ["a fen"])
        Run.stdout = '{"root_status":2}\n'
        with patch.object(fixtures.subprocess, "run", return_value=Run()):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                fixtures.oracle_rows("unused", "unused", ["a fen"])


class PreparedSet(unittest.TestCase):
    def test_prepared_set_is_complete_balanced_and_proven(self):
        path = ROOT / "artifacts/endgame-playing-001/fixture-preparation/fixtures.json"
        if not path.is_file():
            self.skipTest("run prepare_endgame_playing.py to check the real prepared set")
        data = json.loads(path.read_text())
        cases = data["cases"]
        self.assertEqual(len(cases), 32)
        self.assertEqual(len({" ".join(c["fen"].split()[:4]) for c in cases}), 32)
        self.assertEqual({category: sum(c["category"] == category for c in cases)
                          for category in ("five_win", "five_draw", "six_transition")},
                         {"five_win": 12, "five_draw": 12, "six_transition": 8})
        wins = [c for c in cases if c["category"] == "five_win"]
        self.assertEqual(sum(c["initial_outcome"] == "white_win" for c in wins), 6)
        self.assertEqual(sum(c["initial_outcome"] == "black_win" for c in wins), 6)
        for index in range(0, 32, 2):
            self.assertEqual(fixtures.reflected(cases[index]["fen"]), cases[index + 1]["fen"])
            self.assertEqual(cases[index]["initial_wdl_stm"], cases[index + 1]["initial_wdl_stm"])
        for case in cases:
            self.assertTrue(case["initial_legal_moves"])
            if case["category"] == "six_transition":
                proof = case["proof"]
                self.assertTrue(proof["all_legal_moves_capture_into_five"])
                self.assertTrue(proof["no_six_piece_table_used"])
                self.assertEqual(set(proof["root_legal_moves"]),
                                 {c["move"] for c in proof["children"]})
                self.assertGreaterEqual(len(proof["children"]), 2)
                for child in proof["children"]:
                    self.assertEqual(len(fixtures.board_of(child["fen"])), 5)
                    self.assertEqual(child["fen"].split()[4], "0")
                    self.assertEqual(child["parent_move_wdl_stm"], 4 - child["child_wdl_stm"])
            else:
                self.assertEqual(case["pieces"], 5)
                self.assertFalse(fixtures.ambiguous_boundary(case["fen"], case["oracle"]))
        self.assertEqual(sum(int(c["fen"].split()[4]) in (98, 99) for c in cases), 4)


if __name__ == "__main__":
    unittest.main()
