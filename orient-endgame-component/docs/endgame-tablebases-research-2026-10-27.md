# Endgame tablebases and Orient

Research checked: 27 October 2026, New Zealand local date. This note records the
initial feasibility review. The user subsequently clarified that public solved
positions and an attributed Fathom reader fork are allowed while Orient's playing
algorithm remains its own, and approved five-piece integration. Follow the
[implementation report](endgame-tablebases-implementation-2026-10-27.md) and
[setup guide](endgame-tablebases.md) for the resulting implementation and evidence.

## What is solved

Complete standard endgame tablebase material coverage reaches seven pieces,
counting both kings and all pawns. King, rook and pawn versus king and rook is
a five-piece position. Two kings alone are already a trivial draw. For supported
positions, tablebases give a proven win, draw or loss with optimal play; they
do not make every position winning. This does not solve chess from its starting
position. Remaining castling rights and repetition history need separate engine
handling; the move-count rule and the tablebase metric matter as well.

Lichess's February 2026 Op1 release adds a large subset of eight-piece positions
with an opposing white/black pawn pair on the same file. Some extremely lopsided
material classes are excluded. It covers slightly more than half of eight-piece
positions encountered on Lichess, not half of all possible eight-piece positions
(the latter share is about 1.3%). Op1 gives distance to conversion and ignores
the 50-move rule. Complete eight-piece coverage is not supplied by this release.

Sources: [complete seven-piece coverage and Syzygy metrics](https://lichess.org/@/lichess/blog/7-piece-syzygy-tablebases-are-complete/W3WeMyQA),
[Op1 announcement, coverage and metrics](https://lichess.org/@/Lichess/blog/op1-partial-8-piece-tablebase-available/1ptPBDpC).

## Compressed storage

These are approximate cumulative Syzygy totals, including the smaller tables.
The source lists each material-size tier separately; the totals below add them.

| Coverage | Outcome tables (WDL) | Outcome plus progress tables (WDL + DTZ) |
| --- | --- | --- |
| Up to five pieces | 378 MiB, about 0.40 GB | 939 MiB, about 0.98 GB |
| Up to six pieces | About 68 GiB, or 73 GB | About 150 GiB, or 161 GB |
| Up to seven pieces | About 8.6 TiB, or 9.5 TB | About 16.8 TiB, or 18.5 TB |

GB/TB are decimal storage units; MiB/GiB/TiB are binary units. Figures are rounded
from the published collection sizes, not a fresh byte count of every mirror file.
The separate partial eight-piece Op1 collection is 63 TiB, about 69 TB; that is
additional storage, not a complete cumulative eight-piece Syzygy set.

The collections contain many files grouped by material combination. Syzygy uses
separate outcome and distance-to-zero files. WDL tells search the result; DTZ
helps choose moves that make progress while respecting the 50-move rule.
Keeping only WDL reduces storage but requires additional care to convert wins.

Sources: [Lichess size table](https://lichess.org/@/lichess/blog/7-piece-syzygy-tablebases-are-complete/W3WeMyQA),
[Syzygy author's format and compression description](https://github.com/syzygy1/tb),
[Op1 size](https://lichess.org/@/Lichess/blog/op1-partial-8-piece-tablebase-available/1ptPBDpC).

## Practical design options

The existing formats already compress the data heavily. Further lossless
compression is a research possibility, not an established route from an
18-terabyte collection to a small application asset. A small neural model could
approximate tablebase results, but it would need its own correctness proof to
retain the tablebase guarantee. Storing a subset gives exact results only on
covered positions, with normal search for missing data.

If shared tablebase data is accepted, a practical first implementation is an
optional local set through five pieces, roughly one gigabyte including WDL and
DTZ. Keep the tables on disk and read/decompress needed blocks, with a bounded
cache; the engine does not need the entire collection in RAM. Add six-piece
coverage later if measured benefit and storage justify it. Material subsets
also need the smaller and promoted-material tables required by the probe.

An independently written Orient probe could return a proven result for a
supported position and otherwise fall back to the existing search. Missing
files must mean unknown, never draw. Root move selection needs progress
information as well as outcome, and must preserve legal-move, draw-history,
time-budget and cancellation behavior. Draw checks must preserve checkmate's
precedence. Earlier search positions can benefit too: a calculated capture into
a covered ending supplies an exact result for that branch.

A hosted API avoids the large local download, but introduces network latency
and availability into move selection. Local five-piece coverage is the more
predictable starting point for the present local engine.

Sources: [Syzygy format and probing interface](https://github.com/syzygy1/tb),
[Lichess tablebase HTTP API](https://github.com/lichess-org/lila-tablebase),
[outcome versus progress and SSD guidance](https://lichess.org/@/lichess/blog/7-piece-syzygy-tablebases-are-complete/W3WeMyQA).

## Originality decision

[Orient's current provenance document](originality.md) states that no imported
endgame tablebase is incorporated; training accepts verified Orient-only data.
Public tablebases contain solved chess positions rather than a competing
engine's playing implementation, but their results remain external data. Using
them during play would be an explicit change to the documented provenance
boundary, even with an original reader. Keep any such results out of the current
own-data training pipeline unless its data policy is deliberately revised too.

If both implementation and generated data must remain original, independently
implement retrograde analysis, working backwards from terminal positions, and
start with three- and four-piece endings before attempting five. This retains
the existing provenance direction at the cost of substantial implementation
and verification work. Generating all seven-piece tables is far beyond a small
local development task: the published Syzygy generator specifies at least one
terabyte of RAM for that tier.

Source for generation requirements: [Syzygy author's generator documentation](https://github.com/syzygy1/tb).

Neither option establishes a playing-strength gain without a controlled match.
The existing frozen strength-validation conditions would need to record any
tablebase files, hashes and settings used by the candidate and opponents.
