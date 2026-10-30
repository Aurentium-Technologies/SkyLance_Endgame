#!/usr/bin/env python3
"""Black-box lifecycle tests of the actual Orient executable (stdlib only)."""
from __future__ import annotations

import pathlib
import queue
import re
import subprocess
import sys
import threading
import time


class Engine:
    def __init__(self, binary: pathlib.Path):
        self.binary = str(binary)
        self.process = subprocess.Popen([self.binary], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, bufsize=1)
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.seen: list[str] = []
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.put(line.rstrip())
        self.lines.put(None)

    def send(self, text):
        assert self.process.stdin is not None
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def until(self, prefix: str, timeout=5.0):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"timeout waiting for {prefix!r}: {self.seen[-12:]}")
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty:
                raise AssertionError(f"timeout waiting for {prefix!r}: {self.seen[-12:]}") from None
            if line is None:
                raise AssertionError(f"unexpected engine exit {self.process.poll()}: {self.seen[-12:]}")
            self.seen.append(line)
            if line.startswith(prefix):
                return line

    def best(self, timeout=5.0):
        text = self.until("bestmove ", timeout)
        move = text.split()[1]
        if not re.fullmatch(r"(?:[a-h][1-8]){2}[qrbn]?|0000", move):
            raise AssertionError(f"invalid bestmove syntax {text}")
        return move

    def close(self):
        if self.process.poll() is None:
            try:
                self.send("quit")
                self.process.wait(timeout=3)
            except Exception:
                self.process.kill()
                self.process.wait(timeout=3)
                raise
        if self.process.returncode != 0:
            raise AssertionError(f"engine exit code {self.process.returncode}")
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()


def check(value, message):
    if not value:
        raise AssertionError(message)


def run(binary: pathlib.Path):
    start_moves = set(subprocess.check_output([str(binary), "legal", "startpos"], text=True).split())
    check(len(start_moves) == 20, "CLI initial legal moves")
    e = Engine(binary)
    try:
        e.send("uci")
        e.until("uciok")
        check(any(s.startswith("id name SkyLance ") for s in e.seen), "engine identity")
        check("id author Aurentium Technologies" in e.seen, "engine author")
        e.send("setoption name hash value 8")
        e.send("setoption name Threads value 1")
        e.send("isready")
        e.until("readyok")
        e.send("position startpos")
        e.send("go depth 3")
        check(e.best() in start_moves, "depth-limited legal best move")
        check(any(s.startswith("info depth 3 ") for s in e.seen), "completed depth 3")
        check("option name Hash Move Hints type check default false" in e.seen,
              "experimental move-only hash option is advertised and disabled")
        e.send("setoption name Hash Move Hints value true")
        check("option name Direct Legal Moves type check default false" in e.seen,
              "direct legality option is advertised and disabled")
        e.send("setoption name Direct Legal Moves value true")
        e.send("go depth 3")
        check(e.best() in start_moves, "move-only hash hints retain legal UCI result")

        # Replay every reported principal variation through our rules CLI.
        for text in e.seen:
            if " pv " in text:
                pv = text.split(" pv ", 1)[1].split()
                subprocess.run([str(binary), "fen", "startpos", *pv], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

        # Readiness must answer without stopping an active search.
        e.send("go infinite")
        e.send("isready")
        e.until("readyok", 1)
        start = time.monotonic()
        e.send("stop")
        check(e.best(2) in start_moves, "interrupted search retains legal move")
        elapsed = time.monotonic() - start
        check(elapsed < 0.250, f"stop latency {elapsed:.3f}s exceeds 250ms")
        print(f"stop_latency_ms={elapsed * 1000:.2f}")

        # Stop before the search thread has done any useful work.
        e.send("go infinite")
        e.send("stop")
        check(e.best() in start_moves, "immediate stop fallback")
        e.send("position startpos")
        e.send("go nodes 10")
        check(e.best() in start_moves, "node-limited search")
        e.send("go movetime 60")
        started = time.monotonic()
        check(e.best() in start_moves, "time-limited search")
        check(time.monotonic() - started < 1, "movetime exceeded one second")
        e.send("go depth 3 searchmoves e2e4")
        check(e.best() == "e2e4", "searchmoves restriction")

        # Invalid input must retain the last valid position and keep responding.
        for command in ("position fen invalid", "position startpos moves e2e5",
                        "setoption name Hash value -1", "go depth nonsense",
                        "position startpos junk", "go searchmoves e2e5"):
            e.send(command)
            e.until("info string error:")
            e.send("isready")
            e.until("readyok")
        e.send("position startpos moves e2e4 e7e5 g1f3")
        e.send("go depth 2")
        reply = e.best()
        subprocess.run([str(binary), "fen", "startpos", "e2e4", "e7e5", "g1f3", reply],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        for fen in ("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",  # checkmate
                    "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"):  # stalemate
            e.send("position fen " + fen)
            e.send("go depth 2")
            check(e.best() == "0000", "terminal position must return 0000")
        before = sum(s.startswith("bestmove ") for s in e.seen)
        e.send("go infinite")
        time.sleep(0.02)
        e.send("isready")
        e.until("readyok")
        check(sum(s.startswith("bestmove ") for s in e.seen) == before,
              "infinite analysis must wait for stop even at a terminal root")
        e.send("stop")
        check(e.best() == "0000", "stopped infinite terminal analysis")
        e.send("ucinewgame")
        e.send("position startpos")
        e.send("go depth 2")
        check(e.best() in start_moves, "new-game reset")
        e.send("setoption name Pruning value true")
        e.send("go depth 3")
        check(e.best() in start_moves, "selective-search legal result")
        e.send("go infinite")
    finally:
        e.close()

    # EOF during a search must join the worker and shut down cleanly.
    p = subprocess.run([str(binary)], input="uci\nsetoption name Direct Legal Moves value true\nisready\nposition startpos\ngo infinite\n",
                       text=True, capture_output=True, timeout=4)
    check(p.returncode == 0, "EOF shutdown exit code")
    check(p.stdout.count("bestmove ") == 1, "exactly one bestmove per accepted go at EOF")
    print("UCI lifecycle tests passed")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_uci.py /path/to/orient")
    run(pathlib.Path(sys.argv[1]).resolve())
