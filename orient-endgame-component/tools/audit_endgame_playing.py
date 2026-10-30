#!/usr/bin/env python3
"""Replay a fixed endgame on/off sample; games and table labels are not training data."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess

from experiment import compute_child_fds
from tablebase_manifest import verify_tablebase_manifest


PLAYERS = ("Orient-TB-On", "Orient-TB-Off")
RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}
TAG = re.compile(r'^\[([A-Za-z0-9_]+)\s+"((?:\\.|[^"\\])*)"\]\s*$')
UCI = re.compile(r"[a-h][1-8][a-h][1-8][qrbn]?")
BAD_ENDING = re.compile(r"illegal|forfeit|crash|disconnect|stall|time.?out|time.?loss|loses on time|time limit|abandon", re.I)


class AuditError(ValueError):
    pass


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_fen(fen):
    fields = fen.split()
    if len(fields) != 6:
        raise AuditError("Starting positions must retain all six FEN fields")
    return " ".join(fields)


def parse_pgn_text(text):
    """Parse runner UCI notation while retaining each move's exact comments."""
    blocks, headers, body = [], {}, []

    def finish():
        nonlocal headers, body
        if not headers and not body:
            return
        if headers.get("Result") not in RESULTS:
            raise AuditError("Missing or invalid PGN result")
        tokens = re.findall(r"\{[^}]*\}|;[^\n]*|[^\s{};]+", "\n".join(body), re.S)
        moves, ending, comments = [], None, []
        for token in tokens:
            if token.startswith("{") or token.startswith(";"):
                comment = token[1:-1] if token.startswith("{") else token[1:]
                if moves and ending is None:
                    moves[-1]["comments"].append(comment)
                else:
                    comments.append(comment)
                continue
            token = re.sub(r"^\d+\.(?:\.\.)?", "", token)
            if not token or token == "..." or token.startswith("$"):
                continue
            if token in RESULTS:
                if ending is not None:
                    raise AuditError("Multiple movetext results")
                ending = token
            elif ending is not None or not UCI.fullmatch(token):
                raise AuditError("Expected plain UCI runner notation, got " + token)
            else:
                moves.append({"uci": token, "comments": []})
        if ending != headers["Result"]:
            raise AuditError("Movetext result differs from Result tag")
        if "PlyCount" in headers and int(headers["PlyCount"]) != len(moves):
            raise AuditError("PGN PlyCount differs from parsed move count")
        blocks.append({"headers": headers, "moves": moves, "comments": comments})
        headers, body = {}, []

    for line in text.splitlines():
        tag = TAG.match(line.strip())
        if tag:
            if body:
                finish()
            key, value = tag.groups()
            if key in headers:
                raise AuditError("Duplicate PGN tag " + key)
            headers[key] = re.sub(r'\\(["\\])', r'\1', value)
        elif line.strip():
            body.append(line)
    finish()
    return blocks


def seconds(value):
    value = value.strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?ms", value):
        return float(value[:-2])
    if re.fullmatch(r"-?\d+(?:\.\d+)?s?", value):
        return float(value.removesuffix("s")) * 1000
    if re.fullmatch(r"\d+:\d+(?::\d+)?(?:\.\d+)?", value):
        fields = list(map(float, value.split(":")))
        total = 0.0
        for part in fields:
            total = total * 60 + part
        return total * 1000
    return None


def annotations(comments):
    text = ", ".join(comments)
    fields = {match.group(1).lower(): match.group(2).strip()
              for match in re.finditer(r"(?:^|,\s*)([A-Za-z_]+)=([^,]+)", text)}
    reported = None
    # Fastchess prefixes optional eval/depth and engine-reported time.
    first = re.search(r"(?:^|\s)(-?\d+(?:\.\d+)?)s(?:\s*,|\s*$)", text)
    if first:
        reported = float(first.group(1)) * 1000
    for label in ("emt", "time", "elapsed"):
        if label in fields:
            reported = seconds(fields[label])
    bracket_emt = re.search(r"\[%emt\s+([^\]]+)\]", text)
    if bracket_emt:
        reported = seconds(bracket_emt.group(1))
    bracket_clock = re.search(r"\[%clk\s+([^\]]+)\]", text)
    hit = next((fields[k] for k in ("tbhits", "tb", "tb_hits") if k in fields), None)
    if hit is None:
        bracket = re.search(r"\[%tbhits\s+(\d+)\]", text)
        hit = bracket.group(1) if bracket else None
    return {"reported_search_ms": reported,
            "timeleft_ms": seconds(fields["tl"]) if "tl" in fields else seconds(bracket_clock.group(1)) if bracket_clock else None,
            "latency_ms": next((seconds(fields[k]) for k in ("latency", "lat") if k in fields), None),
            "tbhits": int(hit) if hit is not None and re.fullmatch(r"\d+", hit) else None,
            "nodes": int(fields["n"]) if fields.get("n", "").isdigit() else None}


def outcome(wdl):
    if wdl == 4:
        return 1
    if wdl == 0:
        return -1
    if wdl in (1, 2, 3):
        return 0
    raise AuditError("Invalid five-valued WDL")


def fixture_wdl(fixture):
    for value in (fixture.get("initial_wdl_stm"), fixture.get("root_wdl"), fixture.get("wdl"),
                  fixture.get("oracle", {}).get("wdl"),
                  fixture.get("oracle", {}).get("root_wdl"),
                  fixture.get("proof", {}).get("root_wdl")):
        if value is not None:
            outcome(value)
            return value
    raise AuditError("Fixture lacks proven root WDL: " + fixture.get("id", "?"))


def artifact_path(value, base):
    path = Path(value)
    return path if path.is_absolute() else base / path


def verify_plan_artifacts(plan, base):
    """Verify every explicitly frozen path/hash pair, without trusting mutable prose."""
    verified = []

    def walk(value, location):
        if isinstance(value, dict):
            if "path" in value and "sha256" in value:
                path = artifact_path(value["path"], base)
                if not path.is_file() or sha256(path) != value["sha256"]:
                    raise AuditError("Frozen artifact hash differs: " + location)
                verified.append({"field": location, "path": str(path.resolve()), "sha256": value["sha256"]})
            for key, child in value.items():
                walk(child, location + "." + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, location + "[" + str(index) + "]")

    walk(plan, "plan")
    return verified


def load_fixtures(plan, base):
    value = plan.get("fixtures", plan.get("fixtures_manifest"))
    if isinstance(value, list):
        rows = value
    else:
        path = value.get("path") if isinstance(value, dict) else value
        if not isinstance(path, str):
            raise AuditError("Plan lacks fixture list or fixture artifact")
        path = artifact_path(path, base)
        if isinstance(value, dict) and "sha256" in value and value["sha256"] != sha256(path):
            raise AuditError("Fixture artifact hash differs from plan")
        data = json.loads(path.read_text())
        rows = data if isinstance(data, list) else data.get("fixtures", data.get("cases"))
    if not isinstance(rows, list) or not rows:
        raise AuditError("Empty fixture set")
    if len({row["id"] for row in rows}) != len(rows):
        raise AuditError("Duplicate fixture id")
    if len({canonical_fen(row["fen"]) for row in rows}) != len(rows):
        raise AuditError("Duplicate full-FEN fixture")
    for row in rows:
        fixture_wdl(row)
    return rows


class Referee:
    def __init__(self, binary, tables):
        self.process = subprocess.Popen([str(binary), str(tables)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, bufsize=1, pass_fds=compute_child_fds())

    def state(self, fen, moves):
        if any("\n" in value or "\t" in value for value in [fen, *moves]):
            raise AuditError("Invalid protocol delimiter")
        self.process.stdin.write("\t".join(["state", fen, *moves]) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise AuditError("Referee process ended unexpectedly")
        result = json.loads(line)
        if result.get("ok") is False or "error" in result:
            raise AuditError("Referee rejected replay: " + str(result.get("error")))
        return result

    def close(self):
        if not self.process.stdin.closed:
            self.process.stdin.close()
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)
        error = self.process.stderr.read()
        self.process.stdout.close(); self.process.stderr.close()
        if self.process.returncode:
            raise AuditError("Referee failure: " + error[-2000:])


def oracle_exact(state):
    oracle = state.get("oracle", {})
    if state.get("terminal"):
        return oracle.get("exact") is True and oracle.get("wdl") in range(5)
    return bool(oracle.get("available") and oracle.get("exact")
                and not state.get("history_sensitive", False))


def oracle_moves(state):
    rows = state.get("oracle", {}).get("moves", [])
    return {r["uci"]: r["wdl"] for r in rows}


def validate_fixture(fixture, referee):
    state = referee.state(fixture["fen"], [])
    if state["terminal"]:
        raise AuditError("Starting fixture is already terminal")
    if state["piece_count"] == 5:
        if not oracle_exact(state) or outcome(state["oracle"]["wdl"]) != outcome(fixture_wdl(fixture)):
            raise AuditError("Starting five-piece oracle proof differs")
    elif state["piece_count"] == 6:
        values = []
        for move in state["legal"]:
            child = referee.state(fixture["fen"], [move])
            if child["piece_count"] != 5 or child["halfmove"] != 0 or not oracle_exact(child):
                raise AuditError("Six-piece proof must resolve every legal move by a capture into exact five-piece data")
            values.append(-outcome(child["oracle"]["wdl"]))
        if not values or max(values) != outcome(fixture_wdl(fixture)):
            raise AuditError("Starting six-piece capture proof differs")
    else:
        raise AuditError("Playing fixtures must have five or six pieces")
    return state


def expected_for_color(wdl, side, color):
    value = outcome(wdl)
    return value if side == color else -value


def result_for_color(result, color):
    if result == "*":
        return "unfinished"
    if result == "1/2-1/2":
        return "draw"
    return "win" if (result == "1-0") == (color == "white") else "loss"


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    return values[int((len(values) - 1) * fraction)]


def conversion_rates(buckets):
    wins, draws, losses = (buckets.get(key, Counter()) for key in ("known_win", "known_draw", "known_loss"))
    return {"known_wins_converted": {"success": wins.get("win", 0), "total": wins.get("total", 0)},
            "known_draws_held_or_won": {"success": draws.get("draw", 0) + draws.get("win", 0), "total": draws.get("total", 0)},
            "known_losses_resisted": {"success": losses.get("draw", 0) + losses.get("win", 0), "total": losses.get("total", 0)}}


def pgn_quote(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def san_pgn(game, sans, result, replay_failure=None):
    headers = dict(game["headers"])
    if headers["Result"] != result:
        headers["RunnerResult"] = headers["Result"]
    headers["Result"] = result
    headers["PlyCount"] = str(len(sans))
    if replay_failure:
        headers["AuditUnreplayedPlies"] = str(len(game["moves"]) - len(sans))
        headers["AuditReplayFailure"] = replay_failure
    side = headers["FEN"].split()[1]
    number = int(headers["FEN"].split()[5])
    tokens = []
    for index, san in enumerate(sans):
        if side == "w":
            tokens.append(str(number) + ".")
        elif index == 0:
            tokens.append(str(number) + "...")
        tokens.append(san)
        comments = game["moves"][index]["comments"]
        if comments:
            tokens.append("{" + ", ".join(comments).replace("}", "") + "}")
        if side == "b":
            number += 1
        side = "b" if side == "w" else "w"
    tokens.append(result)
    return "\n".join(f'[{key} "{pgn_quote(value)}"]' for key, value in headers.items()) + "\n\n" + " ".join(tokens) + "\n\n"


def audit_games(plan, fixtures, games, referee, runner_log=""):
    expected_games = plan.get("requested_games", len(fixtures) * 2)
    if len(games) != expected_games or expected_games != len(fixtures) * 2:
        raise AuditError("Game count does not equal two assignments per frozen fixture")
    by_fen = {canonical_fen(row["fen"]): row for row in fixtures}
    initial = {row["id"]: validate_fixture(row, referee) for row in fixtures}
    pairs = defaultdict(list)
    summaries, move_rows, human_pgn = [], [], []
    failures, unfinished = [], []
    timings = {player: defaultdict(list) for player in PLAYERS}
    preserving = {player: Counter() for player in PLAYERS}
    opportunities = {player: defaultdict(Counter) for player in PLAYERS}
    category_opportunities = defaultdict(lambda: {player: defaultdict(Counter) for player in PLAYERS})
    transitions = {player: Counter() for player in PLAYERS}
    increment = plan.get("increment_ms", 50)
    maxplies = plan.get("maxplies", plan.get("max_plies", 512))
    for game_number, game in enumerate(games, 1):
        tags = game["headers"]
        if {tags.get("White"), tags.get("Black")} != set(PLAYERS):
            raise AuditError("Unexpected engine names")
        if tags.get("SetUp") != "1":
            raise AuditError("Missing SetUp tag")
        fen = canonical_fen(tags.get("FEN", ""))
        if fen not in by_fen:
            raise AuditError("Game did not start at a declared complete FEN")
        if tags.get("TimeControl") != plan.get("time_control", "5+0.05"):
            raise AuditError("Game time control differs from fixed plan")
        fixture = by_fen[fen]
        pairs[fixture["id"]].append(tags["White"])
        before = initial[fixture["id"]]
        history, sans = [], []
        previous_clock = {"white": plan.get("runner_starting_clock_ms"),
                          "black": plan.get("runner_starting_clock_ms")}
        transition, replay_failure = None, None
        for ply, record in enumerate(game["moves"], 1):
            move = record["uci"]
            side = before["side"]
            player = tags["White" if side == "white" else "Black"]
            if before["terminal"] or move not in before["legal"]:
                replay_failure = "continued_terminal" if before["terminal"] else "illegal_move"
                failure = {"game": game_number, "ply": ply, "engine": player, "reason": replay_failure,
                           "uci": move, "fen": before["fen"]}
                failures.append(failure)
                move_rows.append({**failure, "fixture_id": fixture["id"], "category": fixture["category"],
                                  "replayed": False, "fen_before": before["fen"], "legal": before["legal"]})
                break
            history.append(move)
            after = referee.state(fen, history)
            sans.append(after["last_san"])
            note = annotations(record["comments"])
            clock_delta, clock_budget = None, previous_clock[side]
            if note["timeleft_ms"] is not None:
                timings[player]["timeleft_ms"].append(note["timeleft_ms"])
                if previous_clock[side] is not None:
                    clock_delta = previous_clock[side] + increment - note["timeleft_ms"]
                    timings[player]["clock_derived_ms"].append(clock_delta)
                    if clock_budget > 0:
                        timings[player]["clock_budget_used_fraction"].append(clock_delta / clock_budget)
                    if clock_delta < -2:
                        failures.append({"game": game_number, "ply": ply, "reason": "clock_annotation_increased_beyond_increment"})
                previous_clock[side] = note["timeleft_ms"]
                if note["timeleft_ms"] < -1:
                    failures.append({"game": game_number, "ply": ply, "reason": "negative_clock"})
            for key in ("reported_search_ms", "latency_ms", "tbhits", "nodes"):
                if note[key] is not None:
                    timings[player][key].append(note[key])
            if player == PLAYERS[1] and note["tbhits"] is not None and note["tbhits"] > 0:
                failures.append({"game": game_number, "ply": ply, "reason": "disabled_tables_reported_hits"})
            assessed, retained, chosen, best = False, None, None, None
            if oracle_exact(before):
                options = oracle_moves(before)
                if options:
                    if set(options) != set(before["legal"]) or len(options) != len(before["oracle"]["moves"]):
                        raise AuditError("Oracle alternatives differ from complete legal move set")
                    chosen = outcome(options[move]); best = max(map(outcome, options.values()))
                    retained = chosen == best; assessed = True
                    preserving[player]["assessed"] += 1
                    preserving[player]["preserved" if retained else "degraded"] += 1
            if transition is None and before["piece_count"] == 6 and after["piece_count"] == 5:
                if not oracle_exact(after):
                    value = None
                else:
                    value = -outcome(after["oracle"]["wdl"])
                transition = {"ply": ply, "engine": player, "uci": move,
                              "root_outcome": value, "fixture_best_outcome": outcome(fixture_wdl(fixture)),
                              "preserved_proven_outcome": value == outcome(fixture_wdl(fixture)) if value is not None else None}
                transitions[player]["observed"] += 1
                if value is not None:
                    transitions[player]["assessed"] += 1
                    transitions[player]["preserved" if transition["preserved_proven_outcome"] else "degraded"] += 1
            move_rows.append({"game": game_number, "fixture_id": fixture["id"], "category": fixture["category"],
                              "replayed": True,
                              "ply": ply, "side": side, "engine": player, "uci": move, "san": after["last_san"],
                              "fen_before": before["fen"], "fen_after": after["fen"],
                              "pieces_before": before["piece_count"], "pieces_after": after["piece_count"],
                              "halfmove_before": before["halfmove"], "halfmove_after": after["halfmove"],
                              "repetitions_after": after["repetition_count"],
                              "oracle_assessed": assessed, "chosen_outcome": chosen, "best_outcome": best,
                              "outcome_preserved": retained, "history_sensitive": before.get("history_sensitive", False),
                              "clock_derived_ms": clock_delta, "clock_budget_ms": clock_budget,
                              "clock_budget_used_fraction": clock_delta / clock_budget if clock_delta is not None and clock_budget and clock_budget > 0 else None,
                              **note})
            before = after
        ending_text = " ".join([tags.get("Termination", ""), *game["comments"],
                                *(c for m in game["moves"] for c in m["comments"])])
        result = tags["Result"]
        reliability = BAD_ENDING.search(ending_text)
        if reliability:
            failures.append({"game": game_number, "reason": "runner_reliability_failure", "detail": ending_text})
        if before["terminal"]:
            if result != before["result"]:
                failures.append({"game": game_number, "reason": "runner_result_differs_from_rules",
                                 "runner_result": result, "rules_result": before["result"], "fen": before["fen"]})
            audited_result, termination = before["result"], before["termination"]
        elif reliability or replay_failure:
            audited_result, termination = "*", "runner_failure"
        elif len(history) >= maxplies or result == "*" or re.search(r"adjudicat|maximum|move limit", ending_text, re.I):
            audited_result, termination = "*", "unfinished_cap" if len(history) >= maxplies else "unfinished_adjudication"
            unfinished.append(game_number)
        else:
            raise AuditError("Nonterminal result without a declared cap or failure")
        for color, player in (("white", tags["White"]), ("black", tags["Black"])):
            expected = expected_for_color(fixture_wdl(fixture), initial[fixture["id"]]["side"], color)
            bucket = "known_win" if expected > 0 else "known_loss" if expected < 0 else "known_draw"
            actual = result_for_color(audited_result, color)
            opportunities[player][bucket][actual] += 1
            opportunities[player][bucket]["total"] += 1
            category_opportunities[fixture["category"]][player][bucket][actual] += 1
            category_opportunities[fixture["category"]][player][bucket]["total"] += 1
        summaries.append({"game": game_number, "fixture_id": fixture["id"], "category": fixture["category"],
                          "white": tags["White"], "black": tags["Black"], "runner_result": result,
                          "audited_result": audited_result, "termination": termination, "plies": len(history),
                          "runner_plies": len(game["moves"]), "replay_failure": replay_failure,
                          "final_fen": before["fen"], "transition": transition,
                          "starting_wdl": fixture_wdl(fixture)})
        human_pgn.append(san_pgn(game, sans, audited_result, replay_failure))
    if set(pairs) != {row["id"] for row in fixtures} or any(sorted(sides) != sorted(PLAYERS) for sides in pairs.values()):
        raise AuditError("A fixture lacks exactly one game for each engine assignment")
    runner_failures = [line for line in runner_log.splitlines()
                       if re.search(r"illegal move|loses on time|crash|connection stalls|engine.*(?:stopped|disconnected)|time forfeit", line, re.I)]
    failures.extend({"reason": "runner_log_failure", "detail": line} for line in runner_failures)
    timing_summary = {}
    for player in PLAYERS:
        row = {}
        for key, values in timings[player].items():
            row[key] = {"samples": len(values), "sum": sum(values), "min": min(values),
                        "median": percentile(values, .5), "p95": percentile(values, .95), "max": max(values)}
        row["tbhits_missing_moves"] = sum(m["engine"] == player and m.get("replayed") and m["tbhits"] is None for m in move_rows)
        timing_summary[player] = row
    score = Counter()
    for row in summaries:
        on_color = "white" if row["white"] == PLAYERS[0] else "black"
        score[result_for_color(row["audited_result"], on_color)] += 1
    report = {"schema_version": 1, "status": "complete" if not failures and not unfinished else "needs_review",
              "requested_games": expected_games, "completed_game_records": len(games), "complete_pairs": len(pairs),
              "rule_terminal_games": sum(g["audited_result"] != "*" for g in summaries),
              "unfinished_games": unfinished, "reliability_failures": failures,
              "tables_on_score": dict(score),
              "initial_outcome_results": {p: {k: dict(v) for k, v in buckets.items()} for p, buckets in opportunities.items()},
              "conversion_counts": {p: conversion_rates(buckets) for p, buckets in opportunities.items()},
              "initial_outcome_by_category": {c: {p: {k: dict(v) for k, v in buckets.items()}
                                                   for p, buckets in players.items()}
                                              for c, players in category_opportunities.items()},
              "outcome_preservation": {p: dict(counts) for p, counts in preserving.items()},
              "six_to_five_transitions": {p: dict(counts) for p, counts in transitions.items()},
              "timing": timing_summary, "games": summaries,
              "clock_note": "Reported engine search times and annotation clock deltas are separate. First delta uses runner_starting_clock_ms when declared, otherwise is unknown. Fastchess adds the increment after each move; annotations are rounded to milliseconds.",
              "interpretation": "Fixed endgame sample only; no Elo/strength certification and no training labels."}
    return report, move_rows, "".join(human_pgn)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--pgn", type=Path, required=True)
    parser.add_argument("--referee", type=Path, required=True)
    parser.add_argument("--tables", type=Path)
    parser.add_argument("--runner-log", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    try:
        plan = json.loads(args.plan.read_text())
        base = args.plan.resolve().parent
        verified = verify_plan_artifacts(plan, base)
        fixtures = load_fixtures(plan, base)
        dataset_root = plan.get("tablebases", plan.get("dataset", {})).get("root")
        tables = args.tables or (artifact_path(dataset_root, base) if dataset_root else Path("external/tablebases/syzygy/3-4-5"))
        dataset = verify_tablebase_manifest(tables / "manifest.json")
        referee = Referee(args.referee.resolve(strict=True), tables.resolve(strict=True))
        try:
            report, moves, san = audit_games(plan, fixtures, parse_pgn_text(args.pgn.read_text()), referee,
                                            args.runner_log.read_text() if args.runner_log else "")
        finally:
            referee.close()
    except (AuditError, ValueError, OSError) as error:
        (args.out / "audit-error.json").write_text(json.dumps({"status": "invalid", "error": str(error)}, indent=2) + "\n")
        raise
    report["inputs"] = {key: {"path": str(path.resolve()), "sha256": sha256(path)}
                        for key, path in (("plan", args.plan), ("pgn", args.pgn), ("referee", args.referee))}
    if args.runner_log:
        report["inputs"]["runner_log"] = {"path": str(args.runner_log.resolve()), "sha256": sha256(args.runner_log)}
    report["verified_plan_artifacts"] = verified
    report["verified_dataset"] = dataset
    (args.out / "audit.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (args.out / "move-audit.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in moves))
    decisions = [row for row in moves if row.get("outcome_preserved") is False or row.get("replayed") is False]
    (args.out / "failing-positions.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in decisions))
    (args.out / "games-raw.pgn").write_bytes(args.pgn.read_bytes())
    (args.out / "games-san.pgn").write_text(san)
    print(json.dumps({key: report[key] for key in ("status", "completed_game_records", "complete_pairs", "rule_terminal_games", "tables_on_score", "reliability_failures", "unfinished_games")}, indent=2))


if __name__ == "__main__":
    main()
