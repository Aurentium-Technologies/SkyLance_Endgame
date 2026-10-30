# Endgame playing diagnostic 001 — 28 October 2026

This historical report names supporting files from the wider local research archive. Available public records and separate downloads are listed in the [evidence index](../../evidence/README.md); local-only paths below are not GitHub download links.


Frozen Orient 015 with five-piece tablebases converted all 12 selected
five-piece winning starts, compared with 9 of 12 for the same engine with
probing disabled. Both configurations held every selected five-piece draw.
The trial also exposed a limitation: the enabled configuration lost one drawn
ending after a repetition caused direct probing to give way to ordinary
history-aware search. Address that regression target before expanding coverage
or spending more time on probe compression.

This is a fixed endgame diagnostic, not an Elo estimate or evidence of superiority
to Stockfish. No engine change, replacement candidate, online game, training run or
rating campaign was made for this experiment.

## Frozen comparison

The pre-game plan (local archive: `../artifacts/endgame-playing-001/plan.json`) binds the engine,
settings, runner, referee, fixtures, measurement sources and dataset. All 23
referenced artifact hashes passed post-game verification. Every one of the 290
table files also passed its manifest verification.

| Item | Fixed setting |
| --- | --- |
| Engine on both sides | `orient-015-syzygy`, SHA-256 `49766fc38c62c4e1e4aad83bed2ff28e7d3bb6eba31c9774b7e41ee050dc9b04` |
| Only UCI difference | `SyzygyProbeLimit=5` versus `0` |
| Shared settings | Hash 256 MiB; one thread; classical evaluation; Null Move on; ponder off; Move Overhead 50 ms; SyzygyCache 0 |
| Shared dataset | Same local SyzygyPath, loaded by both; 983,957,920 bytes; manifest SHA-256 `7d4eae2c333da3b8b9e485e0496efc56a07b4452e2bb53e83cfa6bceb9c7a73d` |
| Runner | Pinned local Fastchess v1.8.2-alpha; strict mode; seed 2026102801 |
| Schedule | 32 full-FEN starts, two engine assignments per start; 64 games |
| Time control | 5 seconds plus 50 ms per move, zero runner time margin |
| Compute | Project compute lease; at most three games at once; Intel i7-10810U host |
| Adjudication | Actual rule terminals and automatic draw claims; no evaluation resignation, evaluation draw or tablebase adjudication |
| Safety cap | 256 moves; a capped game would be unfinished, never credited as a conversion or held draw |

The transport trace independently confirms the option values for every game.
Both sides use the same binary and dataset, so loading and initialization are
not confounded with turning probes off. The rejected compact-cache and root-list
experiments remain disabled. The existing 015 checkpoint and profiles are intact.

## Position selection

The fixture manifest (local archive: `../artifacts/endgame-playing-001/fixture-preparation/fixtures.json`)
was frozen before the games. It contains 12 five-piece wins, 12 five-piece draws
and eight six-piece capture transitions. Colour/rank reflections balance the
positions. Five-piece examples cover rook/pawn, pawn, bishop, knight and
two-bishop endings. Four fixtures start at halfmove 98 or 99. The
opening PGN (local archive: `../artifacts/endgame-playing-001/fixture-preparation/openings.pgn`)
preserves all six FEN fields; a transport smoke verified those counters before
the fixed run.

Every legal move at each six-piece start captures the checking queen and reaches
a verified five-piece child. These parents have one-ply minimax proofs from the
complete child set; no general six-piece coverage is claimed. The queen-ending
examples include a winning capture and a drawing alternative. All 16 observed
six-to-five choices preserved the proven root outcome, eight per configuration.

Initial labels were checked with the unchanged upstream Fathom reference helper
and cross-checked by the replay referee. The per-move oracle uses the locally
verified Fathom adapter and dataset; it is not an independently implemented
tablebase decoder. Rule replay checks both Orient legal generators, retains the
complete history, and adjudicates actual mate/draw results itself. These fixtures,
game moves and oracle labels are measurement data only, excluded from training.

## Results

All 64 records replayed successfully: 3,127 legal plies, 32 complete reversed
pairs and 64 actual rule terminals. There were 34 checkmates, 17 fifty-move
draws, 11 insufficient-material draws and two threefold draws. No game reached
the cap; the longest lasted 185 plies. There were no illegal moves, crashes,
time forfeits, result disagreements or missing move annotations.

| Opportunity | Tablebases enabled | Tablebases disabled |
| --- | ---: | ---: |
| Selected five-piece wins converted | 12 / 12 | 9 / 12 |
| Selected five-piece drawn starts held | 24 / 24 | 24 / 24 |
| All proven winning opportunities, including transition cases | 18 / 18 | 15 / 18 |
| All initially drawn opportunities held or won | 27 / 28 | 28 / 28 |
| Initially losing opportunities saved as draws | 3 / 18 | 0 / 18 |
| Six-to-five choices preserving the proven outcome | 8 / 8 | 8 / 8 |

Each drawn fixture gives each configuration two drawn opportunities, one for
each colour assignment. The aggregate enabled score was 18 wins, 30 draws and
16 losses. Retain all games, including the drawn loss; none were removed or
rerun based on their outcome.

The per-move audit assessed history-independent oracle alternatives for 865
enabled moves and 863 disabled moves. Enabled preserved all 865 assessed
outcomes; disabled degraded three wins to draws. This is a conditional metric:
689 enabled moves had repetition-sensitive histories and another eight were
six-piece roots, so 697 enabled moves were outside that per-move assessment.
The unassessed portion includes the drawn loss. A perfect assessed count does
not mean perfect play or complete draw retention.

## Regression target: drawn rook versus bishop ending

PGN record 53, fixture `six_transition-03`, entered a drawn five-piece ending.
The first repeated position occurred at ply 20; at ply 21 the root probe guard
started retaining ordinary history-aware search. At ply 37, `19.Kc1` (`b1c1`)
changed the board/clock tablebase value from draw to loss:

```text
8/8/6B1/1r6/8/2k5/8/1K6 w - - 26 19
```

A fresh-history probe of that FEN gives drawing alternatives `Ka1` and `Ka2`,
and a losing value for `Kc1`. The actual trace retains the full 36-ply prefix
and reports depth 8, score cp -243, bestmove `b1c1`. The game ended in actual
checkmate at ply 48. Preserve the full history when reproducing this case;
resetting to the FEN alone takes a different root-search path.

The full diagnosis (local archive: `../artifacts/endgame-playing-001/diagnosis/README.md`)
also verifies that the chosen move loses with the actual prior history. Its
30-node certificate covers every White reply and one winning Black policy,
reaching actual mate or a history-independent winning capture within seven
further plies. All 25 nonterminal certificate probes agree with unchanged
Fathom, including complete legal alternatives. This avoids inferring an
actual-history loss from a fresh-history tablebase label alone.

The guard follows the integration's deliberate rule: do not return an
unconditional decisive tablebase score when earlier repetitions make it
uncertain. This trial exposes the playing weakness of giving up all root
guidance in that situation. It is not evidence of a corrupt table file or
incorrect raw Fathom lookup. A follow-up should investigate safely retaining
non-losing root alternatives while keeping history-aware adjudication and
search. That requires its own proof, regression tests and frozen comparison;
the guard has not been relaxed here.

## Clocks and probe use

Every enabled/disabled move has clock, node and tablebase-hit annotations.
Enabled reported 3,902,840 total hits; disabled reported zero. Hit totals include
descendant probes and are not counts of distinct positions.

Of the 1,562 enabled moves, 865 were direct tablebase root decisions with zero
search nodes. Their annotated clock consumption had median 0 ms, p95 1 ms and
maximum 4 ms. These are whole-move times rounded to milliseconds, not exact
lookup latency measurements. The other 697 enabled moves used ordinary search;
their median was 170 ms and p95 493 ms. Disabled searched all 1,565 moves, with
median 145 ms and p95 441 ms. These paths and game lengths differ, so their
totals do not establish a general engine speedup or a new optimization gate.

No negative clock or timeout was observed; minimum remaining clock was 100 ms
for both configurations. Fastchess credits the first Fischer increment before
the first `go`: the trace starts at 5,050 ms and credits another increment after
each move. The audit uses that verified convention when reconstructing spent
time. Millisecond rounding and runner scheduling limit finer timing claims.

## Verification and retained evidence

The three new measurement-tool CTest groups pass in release, native, debug and
sanitizer builds: 14 referee cases, eight fixture-selection cases and 15 audit
cases, 37 per build. They cover rule terminals,
history, SAN including promotions/underpromotions and en passant, complete
pairing, caps, clock accounting, illegal moves and artifact validation. The
fixed run then supplies the complete real-game replay. The engine binary and
rules sources remain frozen; the existing integration and optimization reports
retain the earlier release/native/debug/sanitizer and differential evidence.

- Audit and all game summaries (local archive: `../artifacts/endgame-playing-001/analysis/audit.json`)
- Readable SAN games (local archive: `../artifacts/endgame-playing-001/analysis/games-san.pgn`)
- Unmodified runner PGN (local archive: `../artifacts/endgame-playing-001/games.pgn`)
- Move-by-move measurements (local archive: `../artifacts/endgame-playing-001/analysis/move-audit.jsonl`)
- Assessed outcome-degrading moves (local archive: `../artifacts/endgame-playing-001/analysis/failing-positions.jsonl`)
- Supplementary counts (local archive: `../artifacts/endgame-playing-001/analysis/supplementary-counts.json`)
- Full-history regression diagnosis (local archive: `../artifacts/endgame-playing-001/diagnosis/README.md`)
- Runner completion and artifact hashes (local archive: `../artifacts/endgame-playing-001/run-result.json`)
- Native tool test log (local archive: `../artifacts/endgame-playing-001/verification/LastTest.log`)
- Release/debug/sanitizer verification (local archive: `../artifacts/endgame-playing-001/verification/measurement-three-preset-result.json`)
- Measurement source/binary snapshot (local archive: `../artifacts/endgame-playing-001/measurement-snapshot/snapshot.json`)
- Final evidence manifest (local archive: `../artifacts/endgame-playing-001/delivery.json`)

The source snapshot preserves the measurement tools and their build inputs,
separately from frozen 015's original source archive. The dataset remains on
disk under its verified manifest. Reproduction commands are recorded in the
plan; the controller refuses to overwrite an already started run. A new trial
requires a new investigation directory and another pre-game frozen plan.

This selected 32-position sample, including reflected and constructed cases,
does not represent a random population of endgames. Clock-sensitive search is
not bitwise reproducible across machines or schedules. The observations support
the specific conversion and fallback findings above; broader strength and
default-setting decisions require separate controlled evidence.
