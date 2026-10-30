#!/usr/bin/env python3
"""Freeze and run the fixed 64-game endgame diagnostic; never rating/training data."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

from experiment import (artifact, cli_main, compute_lease, metadata, read_json,
                        sha256, utc_now, verify_artifact, write_json)
from matches import engine_args, run_one
from tablebase_manifest import verify_tablebase_manifest

ROOT = Path(__file__).resolve().parents[1]


def prepare(args):
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "plan.json").exists():
        raise ValueError("A frozen plan already exists; use its run action without preparing again")
    fixtures = read_json(args.fixtures)
    cases = fixtures["cases"]
    if (len(cases) != 32 or Counter(c["category"] for c in cases)
            != {"five_win": 12, "five_draw": 12, "six_transition": 8}):
        raise ValueError("Expected the declared 12/12/8 fixed fixture design")
    if len({c["id"] for c in cases}) != 32 or len({c["fen"] for c in cases}) != 32:
        raise ValueError("Endgame fixtures must be unique")
    checkpoint = read_json(args.checkpoint)
    if checkpoint["label"] != "orient-015-syzygy":
        raise ValueError("The fixed baseline is candidate 015")
    verify_artifact(checkpoint["binary"]); verify_artifact(checkpoint["source_archive"])
    for name in ("src/chess.cpp", "include/orient/chess.hpp"):
        if sha256(ROOT / name) != checkpoint["sources"][name]:
            raise ValueError("Referee rules source differs from frozen 015: " + name)
    tables = verify_tablebase_manifest(args.tables)
    if tables["manifest"]["sha256"] != checkpoint["tablebases"]["manifest"]["sha256"]:
        raise ValueError("Tablebase collection differs from candidate 015")
    verify_artifact(fixtures["provenance"]["binary"])
    if fixtures["provenance"]["binary"]["sha256"] != checkpoint["binary"]["sha256"]:
        raise ValueError("Fixture rules binary is not candidate 015")
    book = args.fixtures.resolve().with_name("openings.pgn")
    shared = {"Hash": 256, "Threads": 1, "Ponder": False, "Null Move": True,
              "Use NNUE": False, "Move Overhead": 50,
              "SyzygyPath": tables["root"], "SyzygyCache": 0}
    engines = {}
    for name, limit in (("Orient-TB-On", 5), ("Orient-TB-Off", 0)):
        engines[name] = {**checkpoint["binary"], "name": name,
                         "options": dict(shared, SyzygyProbeLimit=limit)}
    probe = subprocess.run([checkpoint["binary"]["path"]], input="uci\nquit\n",
                           capture_output=True, text=True, timeout=15, check=True)
    advertised = set(re.findall(r"(?m)^option name (.*?) type ", probe.stdout))
    if not set(engines["Orient-TB-On"]["options"]) <= advertised:
        raise ValueError("Frozen engine does not advertise the required options")
    runner = args.fastchess.resolve(strict=True)
    command = ([str(runner), "-output", "format=cutechess"]
               + engine_args(engines["Orient-TB-On"]) + engine_args(engines["Orient-TB-Off"])
               + ["-each", "tc=5+0.05", "timemargin=0", "-openings", "file=" + str(book),
                  "format=pgn", "order=sequential", "-rounds", "32", "-games", "2", "-repeat",
                  "-concurrency", "3", "-maxmoves", "256", "-autosaveinterval", "0",
                  "-srand", "2026102801", "-strict", "-pgnout", "file=" + str(out / "games.pgn"),
                  "append=false", "notation=uci", "nodes=true", "tbhits=true", "timeleft=true",
                  "latency=true", "-log", "file=" + str(out / "engine-trace.log"),
                  "level=trace", "append=false", "engine=true", "realtime=true"])
    source_names = ("tools/run_endgame_playing.py", "tools/experiment.py", "tools/matches.py",
                    "tools/tablebase_manifest.py", "tools/prepare_endgame_playing.py",
                    "tools/endgame_referee.cpp", "tools/audit_endgame_playing.py",
                    "src/chess.cpp", "include/orient/chess.hpp", "src/tablebases.cpp",
                    "include/orient/tablebases.hpp", "third_party/fathom/FORK.json",
                    "third_party/fathom/src/tbprobe.c")
    plan = {"schema_version": 1, "kind": "controlled-endgame-playing-diagnostic",
            "created_utc": utc_now(), "metadata": metadata(),
            "purpose": "endgame conversion/defence/transition evidence, not Elo or training labels",
            "checkpoint": artifact(args.checkpoint), "engine": checkpoint["binary"],
            "source_archive": checkpoint["source_archive"], "runner": artifact(runner),
            "referee": artifact(args.referee), "tablebases": tables,
            "fixtures": cases, "fixtures_artifact": artifact(args.fixtures), "opening_book": artifact(book),
            "engines": engines, "on_name": "Orient-TB-On", "off_name": "Orient-TB-Off",
            "requested_games": 64, "expected_pairs": 32, "time_control": "5+0.05",
            "initial_ms": 5000, "runner_starting_clock_ms": 5050, "increment_ms": 50,
            "clock_convention": "Fastchess credits the first Fischer increment before the first go; verified by transport smoke",
            "max_plies": 512, "max_moves": 256, "concurrency": 3,
            "sources": {name: artifact(ROOT / name) for name in source_names},
            "argv": command, "working_directory": str(out),
            "adjudication": {"evaluation_draw": False, "evaluation_resign": False,
                              "tablebase": False, "automatic_draw_claims": True,
                              "cap": "unfinished, never counted as a successful conversion or a held draw"},
            "selection": "all fixtures and settings frozen before any diagnostic game; no outcome-based resampling"}
    write_json(out / "plan.json", plan)
    print(json.dumps({"plan": str(out / "plan.json"), "games": 64, "pairs": 32,
                      "categories": dict(Counter(c["category"] for c in cases))}, sort_keys=True))


def run(args):
    out = args.out.resolve()
    plan = read_json(out / "plan.json")
    for record in (plan["checkpoint"], plan["engine"], plan["source_archive"], plan["runner"],
                   plan["referee"], plan["fixtures_artifact"], plan["opening_book"]):
        verify_artifact(record)
    for record in plan["sources"].values():
        verify_artifact(record)
    verify_tablebase_manifest(plan["tablebases"]["manifest"]["path"])
    if any((out / name).exists() for name in ("run-start.json", "games.pgn", "run-result.json")):
        raise ValueError("Run already started; inspect durable artifacts before any recovery")
    with compute_lease("fixed-endgame-playing-001"):
        write_json(out / "run-start.json", {"started_utc": utc_now(), "plan": artifact(out / "plan.json")})
        code = run_one(plan["argv"], out / "runner.log", fail_fast=True)
        result = {"ended_utc": utc_now(), "exit_code": code,
                  "status": "runner-completed" if code == 0 else "runner-failed",
                  "plan": artifact(out / "plan.json"), "runner_log": artifact(out / "runner.log")}
        for key, filename in (("pgn", "games.pgn"), ("engine_trace", "engine-trace.log")):
            if (out / filename).is_file():
                result[key] = artifact(out / filename)
        write_json(out / "run-result.json", result)
    print(json.dumps(result, sort_keys=True))
    if code:
        raise ValueError("Endgame runner failed; partial evidence is preserved")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/endgame-playing-001")
    parser.add_argument("--fixtures", type=Path,
                        default=ROOT / "artifacts/endgame-playing-001/fixture-preparation/fixtures.json")
    parser.add_argument("--checkpoint", type=Path,
                        default=ROOT / "artifacts/checkpoints/orient-015-syzygy/checkpoint.json")
    parser.add_argument("--tables", type=Path, default=ROOT / "external/tablebases/syzygy/3-4-5/manifest.json")
    parser.add_argument("--fastchess", type=Path, default=ROOT / "external/tools/fastchess-v1.8.2-alpha/fastchess")
    parser.add_argument("--referee", type=Path, default=ROOT / "build/native/orient-endgame-referee")
    args = parser.parse_args()
    prepare(args) if args.action == "prepare" else run(args)


if __name__ == "__main__":
    cli_main(main)
