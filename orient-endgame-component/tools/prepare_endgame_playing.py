#!/usr/bin/env python3
"""Freeze rule/oracle-selected endgame fixtures, never engine-match training data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from tablebase_manifest import verify_tablebase_manifest


ROOT = Path(__file__).resolve().parents[1]
PIECE_ORDER = "KQRBNP"
WIN_CLASSES = ("KRPvKR", "KPPvKP", "KBPvKP", "KNPvKP", "KNPvKN", "KBBvKN")
DRAW_CLASSES = ("KRPvKR", "KBPvKB", "KNPvKN", "KRNvKR")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifact(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": sha256(path)}


def board_of(fen):
    fields = fen.split()
    if len(fields) != 6:
        raise ValueError("six FEN fields required")
    board = {}
    ranks = fields[0].split("/")
    if len(ranks) != 8:
        raise ValueError("eight FEN ranks required")
    for rank, row in zip(range(7, -1, -1), ranks):
        file = 0
        for character in row:
            if character.isdigit():
                file += int(character)
            elif character in "KQRBNPkqrbnp":
                if file >= 8:
                    raise ValueError("invalid placement")
                board[rank * 8 + file] = character
                file += 1
            else:
                raise ValueError("invalid piece")
        if file != 8:
            raise ValueError("invalid rank width")
    return board


def placement(board):
    ranks = []
    for rank in range(7, -1, -1):
        row, empty = "", 0
        for file in range(8):
            piece = board.get(rank * 8 + file)
            if piece is None:
                empty += 1
            else:
                if empty:
                    row += str(empty)
                    empty = 0
                row += piece
        ranks.append(row + (str(empty) if empty else ""))
    return "/".join(ranks)


def material(fen):
    values = list(board_of(fen).values())
    return ("".join(c * values.count(c) for c in PIECE_ORDER) + "v"
            + "".join(c * values.count(c.lower()) for c in PIECE_ORDER))


def reflected(fen):
    """Rank reflection plus colour/turn swap preserves standard chess rules."""
    fields = fen.split()
    if fields[2] != "-":
        raise ValueError("fixture reflection only supports no castling rights")
    reflected_board = {square ^ 56: value.swapcase() for square, value in board_of(fen).items()}
    ep = fields[3]
    if ep != "-":
        ep = ep[0] + str(9 - int(ep[1]))
    return " ".join((placement(reflected_board), "b" if fields[1] == "w" else "w", "-", ep,
                     fields[4], fields[5]))


def in_check(fen):
    """Rule-only quiet-position filter; frozen Orient validates every final FEN."""
    board = board_of(fen)
    white = fen.split()[1] == "w"
    king = next(square for square, value in board.items() if value == ("K" if white else "k"))
    kf, kr = king % 8, king // 8
    for square, value in board.items():
        if value.isupper() == white:
            continue
        sf, sr = square % 8, square // 8
        df, dr = kf - sf, kr - sr
        kind = value.upper()
        if kind == "P" and abs(df) == 1 and dr == (1 if value.isupper() else -1):
            return True
        if kind == "N" and sorted((abs(df), abs(dr))) == [1, 2]:
            return True
        if kind == "K" and max(abs(df), abs(dr)) == 1:
            return True
        diagonal = abs(df) == abs(dr) and df != 0
        straight = (df == 0) != (dr == 0)
        if ((kind in "BQ" and diagonal) or (kind in "RQ" and straight)):
            step_f = (df > 0) - (df < 0)
            step_r = (dr > 0) - (dr < 0)
            file, rank = sf + step_f, sr + step_r
            while (file, rank) != (kf, kr) and rank * 8 + file not in board:
                file += step_f
                rank += step_r
            if (file, rank) == (kf, kr):
                return True
    return False


def quiet_plausible(fen):
    board = board_of(fen)
    if len(board) != 5 or fen.split()[1] != "w" or in_check(fen):
        return False
    wk = next(s for s, p in board.items() if p == "K")
    bk = next(s for s, p in board.items() if p == "k")
    if max(abs(wk % 8 - bk % 8), abs(wk // 8 - bk // 8)) > 6:
        return False
    return all(p.upper() != "P" or 1 <= square // 8 <= 6 for square, p in board.items())


def outcome_value(wdl):
    if wdl not in range(5):
        raise ValueError("invalid five-way WDL")
    return 1 if wdl == 4 else -1 if wdl == 0 else 0


def absolute_outcome(fen, wdl):
    value = outcome_value(wdl)
    if value == 0:
        return "draw"
    white_wins = (fen.split()[1] == "w") == (value > 0)
    return "white_win" if white_wins else "black_win"


def ambiguous_boundary(fen, oracle):
    """Conservatively avoid quiet rounded-DTZ alternatives on the rule-50 edge."""
    board = board_of(fen)
    clock = int(fen.split()[4])
    for move, _wdl, dtz in oracle["moves"]:
        origin = ord(move[0]) - ord("a") + 8 * (int(move[1]) - 1)
        target = ord(move[2]) - ord("a") + 8 * (int(move[3]) - 1)
        zeroing = board[origin].upper() == "P" or target in board
        if not zeroing and dtz and dtz + clock == 100:
            return True
    return False


def oracle_rows(probe, tables, positions):
    run = subprocess.run([str(probe), str(tables), "0"], input="\n".join(positions) + "\n",
                         capture_output=True, text=True, check=True, timeout=120)
    rows = [json.loads(line) for line in run.stdout.splitlines()]
    if len(rows) != len(positions):
        raise ValueError("oracle result count differs")
    for row in rows:
        if row.get("root_status") != 0:
            raise ValueError("required five-piece oracle result unavailable")
    return rows


def legal_moves(engine, fen):
    return subprocess.run([str(engine), "legal", fen], capture_output=True, text=True,
                          check=True, timeout=10).stdout.split()


def child_fen(engine, fen, move):
    return subprocess.run([str(engine), "fen", fen, move], capture_output=True, text=True,
                          check=True, timeout=10).stdout.strip()


def case_record(identifier, category, fen, oracle, **extra):
    return {"id": identifier, "category": category, "fen": fen, "pieces": len(board_of(fen)),
            "material": material(fen), "initial_wdl_stm": oracle["root_wdl"],
            "initial_outcome": absolute_outcome(fen, oracle["root_wdl"]), "oracle": oracle,
            "history": "fresh starting FEN; moves supplied thereafter retain complete game history",
            **extra}


def make_book(cases):
    games = []
    for number, case in enumerate(cases, 1):
        games.append(f'[Event "Orient endgame playing test 001"]\n[Round "{number}"]\n'
                     f'[CaseId "{case["id"]}"]\n[SetUp "1"]\n[FEN "{case["fen"]}"]\n'
                     '[Result "*"]\n\n*\n')
    return "\n".join(games)


def select_five_piece(corpus, labels, probe, tables):
    if len(corpus) != len(labels):
        raise ValueError("corpus/oracle row count differs")
    rows = [(fen, row, index + 1) for index, (fen, row) in enumerate(zip(corpus, labels))
            if quiet_plausible(fen) and row.get("root_status") == 0]
    used, bases = set(), []

    def choose(category, target_material, predicate, *, halfmove=None):
        # Prefer longer conversion work for wins and an actual losing
        # alternative for drawn positions; retain declared material controls
        # when no such case exists in the rule-only source corpus.
        candidates = sorted(rows, key=lambda item: (
            item[1]["dtz"] == 1 if category == "five_win" else
            not any(outcome_value(move[1]) < 0 for move in item[1]["moves"])))
        for fen, row, source_row in candidates:
            key = " ".join(fen.split()[:4])
            if material(fen) != target_material or key in used or not predicate(row):
                continue
            if halfmove is not None:
                fields = fen.split(); fields[4] = str(halfmove); fen = " ".join(fields)
                row = oracle_rows(probe, tables, [fen])[0]
                if outcome_value(row["root_wdl"]) != 0:
                    continue
            if ambiguous_boundary(fen, row):
                continue
            used.add(key)
            used.add(" ".join(reflected(fen).split()[:4]))
            bases.append((category, fen, row, source_row, halfmove))
            return
        raise ValueError(f"no declared candidate for {category}/{target_material}")

    for name in WIN_CLASSES:
        choose("five_win", name, lambda r: r["root_wdl"] == 4 and 1 <= r["dtz"] <= 40)
    for name in DRAW_CLASSES:
        choose("five_draw", name, lambda r: r["root_wdl"] == 2)
    for name, clock in (("KRRvKR", 98), ("KBBvKN", 99)):
        choose("five_draw", name, lambda r: r["root_wdl"] in (0, 4) and r["dtz"] >= 4,
               halfmove=clock)

    cases, counts = [], {"five_win": 0, "five_draw": 0}
    for category, fen, original, source_row, halfmove in bases:
        pair = [fen, reflected(fen)]
        pair_rows = oracle_rows(probe, tables, pair)
        if pair_rows[0]["root_wdl"] != pair_rows[1]["root_wdl"]:
            raise ValueError("colour/rank reflection changed WDL")
        expected = 1 if category == "five_win" else 0
        if any(outcome_value(row["root_wdl"]) != expected for row in pair_rows):
            raise ValueError("five-piece category does not match fresh oracle")
        for reflected_case, (start, oracle) in enumerate(zip(pair, pair_rows)):
            counts[category] += 1
            cases.append(case_record(f'{category}-{counts[category]:02d}', category, start, oracle,
                                     source_corpus_row=source_row,
                                     construction={"rank_colour_reflected": bool(reflected_case),
                                                   "starting_halfmove_override": halfmove},
                                     proof={"kind": "complete_five_piece_rule50_table",
                                            "raw_wdl": oracle["root_wdl"],
                                            "fifty_move_draw_class": oracle["root_wdl"] in (1, 3)}))
    return cases


def select_transitions(engine, probe, tables):
    cases = []
    for piece, square in (("R", 25), ("B", 28), ("N", 11), ("Q", 33)):
        # White Ka1 is checked by Qb1; each legal reply must capture that queen.
        board = {0: "K", 18: "k", 1: "q", 14: "P", 61: "r", square: piece}
        fen = placement(board) + " w - - 0 1"
        for mirrored, start in enumerate((fen, reflected(fen))):
            legal = legal_moves(engine, start)
            if len(legal) < 2:
                raise ValueError("transition should exercise a real choice between captures")
            parent_board = board_of(start)
            children, fens = [], []
            for move in legal:
                destination = (ord(move[2]) - ord("a")) + 8 * (int(move[3]) - 1)
                captured = parent_board.get(destination)
                following = child_fen(engine, start, move)
                if captured is None or len(board_of(following)) != 5 or following.split()[4] != "0":
                    raise ValueError("not every legal move is a zeroing capture into five pieces")
                fens.append(following)
                children.append({"move": move, "fen": following, "captured": captured})
            for child, oracle in zip(children, oracle_rows(probe, tables, fens)):
                child.update(oracle=oracle, child_wdl_stm=oracle["root_wdl"],
                             parent_move_wdl_stm=4 - oracle["root_wdl"])
            parent_wdl = max(child["parent_move_wdl_stm"] for child in children)
            value = max(outcome_value(child["parent_move_wdl_stm"]) for child in children)
            best = [child["move"] for child in children
                    if outcome_value(child["parent_move_wdl_stm"]) == value]
            case = case_record(f"six_transition-{len(cases) + 1:02d}", "six_transition", start,
                               {"root_wdl": parent_wdl, "root_status": 0,
                                "source": "complete one-ply reduction to five-piece tables"},
                               construction={"kind": "forced_check_capture_choice",
                                             "captor": piece, "rank_colour_reflected": bool(mirrored)},
                               proof={"kind": "complete_one_ply_capture_reduction",
                                      "root_legal_moves": legal, "all_legal_moves_capture_into_five": True,
                                      "children": children, "best_outcome_moves": best,
                                      "no_six_piece_table_used": True})
            cases.append(case)
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "artifacts/checkpoints/orient-015-syzygy/checkpoint.json")
    parser.add_argument("--tablebase-manifest", type=Path, default=ROOT / "external/tablebases/syzygy/3-4-5/manifest.json")
    parser.add_argument("--reference-probe", type=Path, default=ROOT / "build/native/orient-tablebase-reference")
    parser.add_argument("--corpus", type=Path, default=ROOT / "artifacts/investigations/tablebases-001/cache/positions.fen")
    parser.add_argument("--source-oracle", type=Path, default=ROOT / "artifacts/investigations/tablebases-001/comparison/material-orient-tablebase-reference-0.jsonl")
    parser.add_argument("--source-comparison", type=Path, default=ROOT / "artifacts/investigations/tablebases-001/comparison/result.json")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/endgame-playing-001/fixture-preparation")
    args = parser.parse_args()
    cp = json.loads(args.checkpoint.read_text())
    if cp.get("label") != "orient-015-syzygy":
        raise ValueError("candidate 015 is required")
    for record in (cp["binary"], cp["source_archive"]):
        if sha256(record["path"]) != record["sha256"]:
            raise ValueError("frozen candidate artifact differs")
    dataset = verify_tablebase_manifest(args.tablebase_manifest)
    comparison = json.loads(args.source_comparison.read_text())
    if sha256(args.corpus) != comparison["fixtures_sha256"]:
        raise ValueError("source oracle/corpus identity differs")
    expected_oracle = comparison["outputs"]["material-orient-tablebase-reference-0"]["sha256"]
    if sha256(args.source_oracle) != expected_oracle:
        raise ValueError("saved reference oracle differs")
    upstream = json.loads((ROOT / "third_party/fathom/UPSTREAM.json").read_text())
    for relative, expected in upstream["upstream_files"].items():
        if sha256(ROOT / "external/fathom-upstream" / relative) != expected:
            raise ValueError("unchanged reference reader source differs")
    corpus = args.corpus.read_text().splitlines()
    labels = [json.loads(line) for line in args.source_oracle.read_text().splitlines()]
    engine = Path(cp["binary"]["path"])
    cases = select_five_piece(corpus, labels, args.reference_probe, dataset["root"])
    cases += select_transitions(engine, args.reference_probe, dataset["root"])
    if len(cases) != 32 or len({" ".join(c["fen"].split()[:4]) for c in cases}) != 32:
        raise ValueError("expected exactly 32 distinct board/turn fixture cases")
    for case in cases:
        legal = legal_moves(engine, case["fen"])
        if not legal:
            raise ValueError("starting fixture is terminal")
        case["initial_legal_moves"] = legal
    data = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": "paired endgame playing diagnostic only; excluded from neural training and final rating evidence",
            "expected_cases": 32, "expected_games": 64,
            "selection_protocol": {"five_win_base_classes": list(WIN_CLASSES),
                                   "five_draw_base_classes": list(DRAW_CLASSES),
                                   "winning_dtz_range": [1, 40],
                                   "winning_dtz_preference": "2..40; permit DTZ1 pawn/capture progress when no eligible longer case exists",
                                   "ordinary_draw_preference": "prefer a losing alternative; retain declared material controls if unavailable",
                                   "avoid_ambiguous_rule50_boundary": True,
                                   "near_fifty_classes": {"KRRvKR": 98, "KBBvKN": 99},
                                   "base_side": "white", "balance": "rank reflection and colour/turn swap",
                                   "order": "first eligible source-corpus row per declared class; no on/off game-result filtering",
                                   "six_piece": "all legal root moves capture into independently probed five-piece children"},
            "provenance": {"checkpoint": artifact(args.checkpoint), "binary": cp["binary"],
                           "source_archive": cp["source_archive"], "tablebases": dataset,
                           "corpus": artifact(args.corpus), "source_oracle": artifact(args.source_oracle),
                           "source_comparison": artifact(args.source_comparison),
                           "reference_probe": artifact(args.reference_probe),
                           "reference_upstream_commit": upstream["commit"],
                           "preparer_source": artifact(Path(__file__))},
            "cases": cases}
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "fixtures.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (args.out / "openings.pgn").write_text(make_book(cases))
    print(json.dumps({"fixtures": str((args.out / "fixtures.json").resolve()),
                      "book": str((args.out / "openings.pgn").resolve()),
                      "cases": len(cases), "expected_games": 64,
                      "counts": {category: sum(c["category"] == category for c in cases)
                                 for category in ("five_win", "five_draw", "six_transition")}}, indent=2))


if __name__ == "__main__":
    main()
