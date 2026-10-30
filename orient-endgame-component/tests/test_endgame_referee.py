#!/usr/bin/env python3
"""Functional rule/SAN/oracle checks for the experiment's replay referee."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get("ORIENT_REFEREE_BINARY", ROOT / "build/release/orient-endgame-referee")).resolve()
TABLES = os.environ.get("ORIENT_SYZYGY_PATH")
if __name__ == "__main__":
    if len(sys.argv) > 1:
        BINARY = Path(sys.argv[1]).resolve()
    if len(sys.argv) > 2:
        TABLES = sys.argv[2]
# Explicit CLI/CTest paths must fail when broken. Discovery can run the pure
# Python checks before a build, without mistaking unittest's argv for binaries.
REFEREE_AVAILABLE = __name__ == "__main__" or BINARY.is_file()
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class Referee:
    def __init__(self, tables=None):
        self.process = subprocess.Popen([str(BINARY), str(tables) if tables else "--no-oracle"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, bufsize=1)

    def state(self, fen, *moves):
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write("\t".join(("state", fen, *moves)) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise AssertionError("referee closed before a response")
        return json.loads(line)

    def close(self):
        assert self.process.stdin is not None
        self.process.stdin.close()
        self.process.wait(timeout=10)
        assert self.process.stdout is not None and self.process.stderr is not None
        error = self.process.stderr.read()
        self.process.stdout.close(); self.process.stderr.close()
        if self.process.returncode:
            raise AssertionError(error)


@unittest.skipUnless(REFEREE_AVAILABLE, "build the referee or set ORIENT_REFEREE_BINARY")
class RuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = Referee()

    @classmethod
    def tearDownClass(cls):
        cls.ref.close()

    def test_start_and_ordinary_san(self):
        state = self.ref.state(START, "e2e4", "e7e5", "g1f3")
        self.assertTrue(state["ok"])
        self.assertFalse(state["terminal"])
        self.assertEqual(state["piece_count"], 32)
        self.assertEqual(state["san_moves"], ["e4", "e5", "Nf3"])
        self.assertEqual(state["side"], "black")
        self.assertEqual(state["oracle"]["status"], "disabled")

    def test_checkmate_precedes_clock_draw(self):
        state = self.ref.state("7k/6Q1/6K1/8/8/8/8/8 b - - 100 51")
        self.assertTrue(state["terminal"])
        self.assertEqual((state["result"], state["termination"]), ("1-0", "checkmate"))
        self.assertEqual(state["oracle"]["wdl"], 0)

    def test_stalemate_and_insufficient(self):
        stale = self.ref.state("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        self.assertEqual((stale["result"], stale["termination"]), ("1/2-1/2", "stalemate"))
        bare = self.ref.state("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        self.assertEqual(bare["termination"], "insufficient_material")

    def test_fifty_and_pawn_reset(self):
        state = self.ref.state("4k3/8/8/8/8/8/8/R3K3 w - - 100 51")
        self.assertEqual(state["termination"], "fifty_move")
        pawn = self.ref.state("4k3/8/8/8/8/8/P7/R3K3 w - - 99 51", "a2a3")
        self.assertTrue(pawn["ok"])
        self.assertFalse(pawn["terminal"])
        self.assertEqual(pawn["halfmove"], 0)
        self.assertEqual(pawn["last_san"], "a3")

    def test_threefold_uses_complete_history(self):
        cycle = ("g1f3", "g8f6", "f3g1", "f6g8")
        state = self.ref.state(START, *(cycle * 2))
        self.assertEqual(state["repetition_count"], 3)
        self.assertTrue(state["history_sensitive"])
        self.assertEqual(state["termination"], "threefold")
        fresh = self.ref.state(state["fen"])
        self.assertFalse(fresh["terminal"])
        self.assertEqual(fresh["repetition_count"], 1)

    def test_en_passant_san_and_material(self):
        state = self.ref.state("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6")
        self.assertTrue(state["ok"])
        self.assertEqual(state["last_san"], "exd6")
        self.assertEqual(state["piece_count"], 3)
        self.assertEqual(state["halfmove"], 0)

    def test_promotion_and_stalemate(self):
        fen = "8/1P6/k7/8/1K6/8/8/8 w - - 0 1"
        rook = self.ref.state(fen, "b7b8r")
        self.assertEqual(rook["last_san"], "b8=R")
        self.assertFalse(rook["terminal"])
        queen = self.ref.state(fen, "b7b8q")
        self.assertEqual(queen["last_san"], "b8=Q")
        self.assertEqual(queen["termination"], "stalemate")

    def test_castling_and_checkmate_san(self):
        state = self.ref.state("4k3/8/8/8/8/8/8/4K2R w K - 0 1", "e1g1")
        self.assertEqual(state["last_san"], "O-O")
        mate = self.ref.state("7k/6r1/5KQ1/8/8/8/8/8 w - - 0 1", "g6g7")
        self.assertEqual(mate["last_san"], "Qxg7#")
        self.assertEqual(mate["termination"], "checkmate")

    def test_san_disambiguation_file_rank_and_both(self):
        file = self.ref.state("4k3/8/8/8/8/8/3N1N2/4K3 w - - 0 1", "d2e4")
        self.assertEqual(file["last_san"], "Nde4")
        rank = self.ref.state("4k3/8/8/8/8/R7/8/R3K3 w - - 0 1", "a1a2")
        self.assertEqual(rank["last_san"], "R1a2")
        both = self.ref.state("7k/8/8/8/8/1N6/8/KN3N2 w - - 0 1", "b1d2")
        self.assertEqual(both["last_san"], "Nb1d2")

    def test_error_and_recovery(self):
        self.assertFalse(self.ref.state(START, "e2e5")["ok"])
        self.assertFalse(self.ref.state("not a fen")["ok"])
        state = self.ref.state(START)
        self.assertTrue(state["ok"])
        self.assertEqual(len(state["legal"]), 20)
        self.assertFalse(self.ref.state("4k3/8/8/8/8/8/8/4K3 w - - 0 1", "e1e2")["ok"])


@unittest.skipUnless(TABLES, "set ORIENT_SYZYGY_PATH for oracle checks")
@unittest.skipUnless(REFEREE_AVAILABLE, "build the referee or set ORIENT_REFEREE_BINARY")
class OracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = Referee(TABLES)

    @classmethod
    def tearDownClass(cls):
        cls.ref.close()

    def test_proven_win_and_complete_alternatives(self):
        state = self.ref.state("6k1/8/8/8/8/8/8/K2Q4 w - - 0 1")
        oracle = state["oracle"]
        self.assertTrue(oracle["available"] and oracle["exact"])
        self.assertEqual(oracle["wdl"], 4)
        self.assertEqual({item["uci"] for item in oracle["moves"]}, set(state["legal"]))
        self.assertIn(oracle["suggested"], state["legal"])

    def test_history_sensitive_is_not_an_exact_oracle(self):
        state = self.ref.state("7k/8/8/8/8/8/Q7/4K3 w - - 0 1", "a2a3", "h8g8", "a3a2", "g8h8")
        self.assertTrue(state["history_sensitive"])
        self.assertTrue(state["oracle"]["available"])
        self.assertFalse(state["oracle"]["exact"])

    def test_rounded_rule50_boundary_is_not_exact(self):
        fen = "7k/8/5KQ1/8/8/8/8/8 w - - 0 1"
        base = self.ref.state(fen)
        distance = next(item["dtz"] for item in base["oracle"]["moves"] if 1 < item["dtz"] < 100)
        fields = fen.split(); fields[4] = str(100 - distance)
        boundary = self.ref.state(" ".join(fields))
        self.assertTrue(boundary["oracle"]["dtz_boundary_sensitive"])
        self.assertFalse(boundary["oracle"]["exact"])

    def test_six_piece_is_unsupported(self):
        state = self.ref.state("5r2/8/8/8/1R6/2k5/6P1/Kq6 w - - 0 1")
        self.assertEqual(state["piece_count"], 6)
        self.assertEqual(state["oracle"]["status"], "unsupported")
        self.assertFalse(state["oracle"]["exact"])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
