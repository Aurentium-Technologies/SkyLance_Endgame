"""Small independent audit regressions; no engine games or network are run."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from audit_endgame_playing import (AuditError, PLAYERS, annotations, audit_games,
                                    canonical_fen, fixture_wdl, outcome, parse_pgn_text,
                                    sha256, validate_fixture, verify_plan_artifacts)


FEN = "7k/p7/5KQ1/8/8/8/R7/8 w - - 0 1"
FIXTURE = {"id": "five-win-01", "category": "five_win", "fen": FEN, "wdl": 4}
PLAN = {"requested_games": 2, "time_control": "5+0.05", "initial_ms": 5000,
        "runner_starting_clock_ms": 5050, "increment_ms": 50, "maxplies": 512}


def pgn(white, black, result="1-0", move="g6g7", hits=None):
    if hits is None:
        hits = 1 if white == PLAYERS[0] else 0
    return (f'[Event "Audit fixture"]\n[White "{white}"]\n[Black "{black}"]\n'
            f'[Result "{result}"]\n[SetUp "1"]\n[FEN "{FEN}"]\n'
            '[TimeControl "5+0.05"]\n[PlyCount "1"]\n[Termination "normal"]\n\n'
            f'1. {move} {{+M1/0 0.000s, tl=5.100s, latency=0.000s, n=0, tbhits={hits}, White mates}}\n{result}\n\n')


def paired_pgn():
    return pgn(PLAYERS[0], PLAYERS[1]) + pgn(PLAYERS[1], PLAYERS[0])


class FakeReferee:
    def __init__(self, *, terminal=True, exact=True):
        self.terminal, self.exact = terminal, exact

    def state(self, fen, moves):
        value = {"ok": True, "fen": fen, "side": "white", "piece_count": 5,
                 "legal": ["g6g7", "a2a6"], "halfmove": 0, "repetition_count": 1,
                 "history_sensitive": False, "terminal": False, "result": "*", "termination": "",
                 "last_san": "", "oracle": {"available": True, "exact": self.exact, "wdl": 4,
                 "dtz": 1, "moves": [{"uci": "g6g7", "wdl": 4, "dtz": 1}, {"uci": "a2a6", "wdl": 2, "dtz": 0}]}}
        if moves:
            value.update(side="black", legal=[] if self.terminal else ["h8g8"], halfmove=1,
                         last_san="Qg7#" if moves[-1] == "g6g7" else "Ra6",
                         terminal=self.terminal, result="1-0" if self.terminal else "*",
                         termination="checkmate" if self.terminal else "")
            value["oracle"] = {"available": True, "exact": self.exact, "wdl": 0, "dtz": 0, "moves": []}
        return value


class AuditTests(unittest.TestCase):
    def test_parser_retains_per_ply_annotations_and_pair(self):
        games = parse_pgn_text(paired_pgn())
        self.assertEqual(len(games), 2)
        self.assertEqual(games[0]["moves"][0]["uci"], "g6g7")
        self.assertIn("tbhits=1", games[0]["moves"][0]["comments"][0])

    def test_clock_and_tablebase_annotations_match_actual_runner_format(self):
        row = annotations(["+M1/0 0.000s, tl=5.100s, latency=0.003s, n=0, tbhits=1, White mates"])
        self.assertEqual(row["reported_search_ms"], 0)
        self.assertEqual(row["timeleft_ms"], 5100)
        self.assertEqual(row["latency_ms"], 3)
        self.assertEqual(row["tbhits"], 1)
        self.assertIsNone(annotations(["+0.00/1 0.001s"])["tbhits"])
        bracket = annotations(["[%emt 0:00:00.125] [%clk 0:00:04.975]"])
        self.assertEqual(bracket["reported_search_ms"], 125)
        self.assertEqual(bracket["timeleft_ms"], 4975)

    def test_equal_winning_opportunities_swapped_assignments_and_san(self):
        report, moves, san = audit_games(PLAN, [FIXTURE], parse_pgn_text(paired_pgn()), FakeReferee())
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["complete_pairs"], 1)
        self.assertEqual(report["tables_on_score"], {"win": 1, "loss": 1})
        for player in PLAYERS:
            self.assertEqual(report["initial_outcome_results"][player]["known_win"]["win"], 1)
            self.assertEqual(report["initial_outcome_results"][player]["known_loss"]["loss"], 1)
        self.assertTrue(all(row["outcome_preserved"] for row in moves))
        self.assertTrue(all(row["clock_derived_ms"] == 0 for row in moves))
        self.assertIn("Qg7#", san)
        self.assertNotIn("1. g6g7", san)

    def test_missing_first_clock_is_unknown_instead_of_assumed(self):
        plan = {k: v for k, v in PLAN.items() if k != "runner_starting_clock_ms"}
        _, moves, _ = audit_games(plan, [FIXTURE], parse_pgn_text(paired_pgn()), FakeReferee())
        self.assertTrue(all(row["clock_derived_ms"] is None for row in moves))

    def test_missing_or_duplicate_engine_assignment_rejected(self):
        games = parse_pgn_text(pgn(PLAYERS[0], PLAYERS[1]) * 2)
        with self.assertRaises(AuditError):
            audit_games(PLAN, [FIXTURE], games, FakeReferee())
        with self.assertRaises(AuditError):
            audit_games(PLAN, [FIXTURE], games[:1], FakeReferee())

    def test_illegal_move_and_result_mismatch_reported(self):
        games = parse_pgn_text(paired_pgn())
        games[0]["moves"][0]["uci"] = "a1a8"
        report, rows, san = audit_games(PLAN, [FIXTURE], games, FakeReferee())
        self.assertEqual(report["status"], "needs_review")
        self.assertEqual(report["reliability_failures"][0]["reason"], "illegal_move")
        self.assertEqual(report["games"][0]["audited_result"], "*")
        self.assertFalse(rows[0]["replayed"])
        self.assertIn('[AuditReplayFailure "illegal_move"]', san)
        games = parse_pgn_text(paired_pgn())
        games[0]["headers"]["Result"] = "0-1"
        report, _, _ = audit_games(PLAN, [FIXTURE], games, FakeReferee())
        self.assertEqual(report["reliability_failures"][0]["reason"], "runner_result_differs_from_rules")
        self.assertEqual(report["games"][0]["audited_result"], "1-0")

    def test_disabled_table_hits_are_reliability_failure(self):
        games = parse_pgn_text(pgn(PLAYERS[0], PLAYERS[1]) + pgn(PLAYERS[1], PLAYERS[0], hits=1))
        report, _, _ = audit_games(PLAN, [FIXTURE], games, FakeReferee())
        self.assertEqual(report["status"], "needs_review")
        self.assertIn("disabled_tables_reported_hits", [r["reason"] for r in report["reliability_failures"]])

    def test_incomplete_oracle_alternatives_are_rejected(self):
        class Incomplete(FakeReferee):
            def state(self, fen, moves):
                state = super().state(fen, moves)
                state["oracle"]["moves"] = state["oracle"]["moves"][:1]
                return state
        with self.assertRaises(AuditError):
            audit_games(PLAN, [FIXTURE], parse_pgn_text(paired_pgn()), Incomplete())

    def test_capped_nonterminal_is_unfinished_not_draw(self):
        games = parse_pgn_text(pgn(PLAYERS[0], PLAYERS[1], "1/2-1/2") + pgn(PLAYERS[1], PLAYERS[0], "1/2-1/2"))
        plan = dict(PLAN, maxplies=1)
        report, _, san = audit_games(plan, [FIXTURE], games, FakeReferee(terminal=False))
        self.assertEqual(report["rule_terminal_games"], 0)
        self.assertEqual(report["unfinished_games"], [1, 2])
        self.assertEqual(report["tables_on_score"], {"unfinished": 2})
        self.assertIn('[RunnerResult "1/2-1/2"]', san)
        self.assertIn('[Result "*"]', san)

    def test_history_sensitive_oracle_is_not_assessed_as_error(self):
        class HistoryReferee(FakeReferee):
            def state(self, fen, moves):
                value = super().state(fen, moves)
                if moves:
                    value["history_sensitive"] = True
                return value
        # Known fixture remains exact; sensitivity only after its move.
        report, _, _ = audit_games(PLAN, [FIXTURE], parse_pgn_text(paired_pgn()), HistoryReferee())
        self.assertEqual(report["status"], "complete")

    def test_rule_draw_variants_are_normalized(self):
        self.assertEqual([outcome(i) for i in range(5)], [-1, 0, 0, 0, 1])
        with self.assertRaises(AuditError):
            outcome(5)

    def test_parser_rejects_missing_result_san_and_wrong_ply_count(self):
        for raw in (paired_pgn().replace("g6g7", "Qg7#"), paired_pgn().replace('[PlyCount "1"]', '[PlyCount "2"]'),
                    pgn(PLAYERS[0], PLAYERS[1]).rstrip()[:-3]):
            with self.subTest(raw=raw[:50]), self.assertRaises(AuditError):
                parse_pgn_text(raw)
        with self.assertRaises(AuditError):
            canonical_fen("8/8/8/8/8/8/8/8 w - -")

    def test_six_piece_proof_checks_every_legal_capture(self):
        class SixReferee(FakeReferee):
            def state(self, fen, moves):
                value = super().state(fen, moves)
                if not moves:
                    value["piece_count"] = 6
                    value["legal"] = ["a1b1", "d2b1"]
                else:
                    value["halfmove"] = 0
                    value["oracle"]["wdl"] = 0 if moves[-1] == "d2b1" else 4
                return value
        fixture = deepcopy(FIXTURE)
        self.assertEqual(validate_fixture(fixture, SixReferee())["piece_count"], 6)
        class BadSix(SixReferee):
            def state(self, fen, moves):
                value = super().state(fen, moves)
                if moves and moves[-1] == "a1b1": value["piece_count"] = 6
                return value
        with self.assertRaises(AuditError):
            validate_fixture(fixture, BadSix())

    def test_frozen_artifact_hashes_checked_recursively(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            frozen = root / "binary"
            frozen.write_bytes(b"frozen bytes")
            plan = {"engines": [{"binary": {"path": "binary", "sha256": sha256(frozen)}}]}
            verified = verify_plan_artifacts(plan, root)
            self.assertEqual(verified[0]["field"], "plan.engines[0].binary")
            frozen.write_bytes(b"changed bytes")
            with self.assertRaises(AuditError):
                verify_plan_artifacts(plan, root)

    def test_frozen_fixture_wdl_schema(self):
        self.assertEqual(fixture_wdl({"initial_wdl_stm": 4}), 4)
        self.assertEqual(fixture_wdl({"oracle": {"root_wdl": 0}}), 0)


if __name__ == "__main__":
    unittest.main()
