#!/usr/bin/env python3
"""Exercise real local-table UCI lifecycle without network or online games."""
import os
from pathlib import Path
import queue
import sys
import tempfile
import time

from test_uci import Engine, check


def run(binary, tables):
    with tempfile.TemporaryDirectory(prefix="Orient Tables ") as temporary:
        alias = Path(temporary) / "Case Sensitive Tables"
        alias.symlink_to(tables.resolve(), target_is_directory=True)
        engine = Engine(binary)
        try:
            engine.send("uci"); engine.until("uciok")
            check(any("option name SyzygyCache " in s for s in engine.seen), "cache option advertised")
            engine.send("setoption name SyzygyCache value 4")
            engine.send(f"setoption name SyzygyPath value {alias}")
            engine.send("isready"); engine.until("readyok")
            check(any(s == "info string syzygy ready pieces 5 cache_mib 4" for s in engine.seen), "actual tables acknowledged")
            fen = "6k1/8/8/8/8/8/8/K2Q4 w - - 0 1"
            engine.send("position fen " + fen)
            start = time.monotonic(); engine.send("go movetime 100")
            move = engine.best()
            check(move != "0000" and time.monotonic() - start < 2, "finite table search returns promptly")
            check(any("tbhits 1" in s and "score cp 25000" in s for s in engine.seen), "proven outcome uses cp band and tbhits")
            engine.send("position fen " + fen); engine.send("go infinite")
            deadline = time.monotonic() + 0.15
            while time.monotonic() < deadline:
                try:
                    text = engine.lines.get(timeout=0.02)
                except queue.Empty:
                    continue
                check(text is not None and not text.startswith("bestmove "), "infinite analysis must wait for stop")
            engine.send("stop"); check(engine.best() != "0000", "stop releases infinite table result")
            engine.send("setoption name SyzygyProbeLimit value 0")
            engine.send("position fen " + fen); engine.send("go depth 2")
            previous = len(engine.seen); engine.best()
            check(all(" tbhits 0 " in s for s in engine.seen[previous:] if s.startswith("info depth ")), "limit zero disables probes")
            engine.send("setoption name SyzygyProbeLimit value 5")
            engine.send("position fen " + fen); engine.send("go infinite")
            engine.send("setoption name SyzygyPath value /unavailable/orient/tables")
            engine.best(); engine.send("isready"); engine.until("readyok")
            check(any("syzygy unavailable" in s for s in engine.seen), "path change safely joins worker")
            engine.send("position fen " + fen); engine.send("go depth 2")
            check(engine.best() != "0000", "missing directory retains ordinary search")
            engine.send(f"setoption name SyzygyPath value {alias}")
            engine.send("setoption name Clear Hash")
            engine.send("ucinewgame"); engine.send("isready"); engine.until("readyok")
            engine.send("position fen " + fen); engine.send("go depth 1")
            check(engine.best() != "0000", "tables recover after path reset and Clear Hash")
        finally:
            engine.close()
    print("Real-table UCI configuration, deadlines, stop and infinite-analysis checks passed")


if __name__ == "__main__":
    directory = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("ORIENT_SYZYGY_PATH")
    if not directory:
        print("Set ORIENT_SYZYGY_PATH for real-table UCI tests")
        raise SystemExit(77)
    run(Path(sys.argv[1]).resolve(), Path(directory))
