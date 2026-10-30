# Search correctness and development

Orient uses one search thread, iterative deepening, alpha-beta with principal
variation search, quiescence with all check evasions, and a transposition table.
Move ordering uses the cached move, original static exchange evaluation, killer
moves and quiet-move history. Aspiration windows widen on failed searches.
Null-move pruning, late-move reductions and futility pruning are individual
options. Null Move passed the complete two-stage audit in
`artifacts/investigations/null-move-retained-001/result.json` and is retained for
subsequent baselines through explicit `Null Move=true`. Its compiled default
remains off pending a separately verified release promotion. Late-move reductions
and futility remain experimental and disabled until controlled matches retain them.

`Fast Quiescence` is a separate, default-off speed candidate. Outside check it
generates legal captures and all promotions directly, preserving their reference
ordering. Any such move proves the position is not stalemate; if none exists, an
early-exit legal-move query distinguishes a quiet position from stalemate before
stand pat. In check the search still generates every legal evasion. Differential
tests compare exact work and results with the full legal-generation path,
including neural evaluation. Timing and strength evidence are still required.

`Direct Legal Moves` is another default-off candidate. It keeps the same
pseudo-legal generator and ordering, then checks the moving king against a
hypothetical occupancy without modifying the position. Captures are removed
from the enemy attack-source bitboards as well as occupancy. En passant removes
its off-target captured pawn; castling relocates the rook for the final-square
check and retains the reference generator's start/transit checks. Promotions
change occupancy in the same way as other moves for own-king safety.

The original make/unmake legality filter remains available as the reference.
The direct path also supplies tactical and early-exit existence queries. Search
selects all three together, including terminal/draw checks and check evasions.
This is independent of `Fast Quiescence`: the latter controls which moves are
requested outside check. The direct option controls how requested moves are
filtered for legality. The direct path must preserve exact move order, state,
search work and results before timing or strength claims are considered.

Correctness coverage includes 100,000 randomized reversible plies with direct/
reference ordered-list comparisons, separate tactical/existence comparisons,
en-passant check evasions and discovered attacks, double checks, king-capture
x-rays, castling and promotions. `test_chess --extended-direct` runs the canonical
perft fixtures through the direct method, including start position depth six.
Both the native and portable release gates run reference and direct depth six.

## Repetition context in cached scores

A board position alone does not identify its searchable game state. A different
reversible history can supply a threefold-repetition escape, even when a cached
history-free search found a forced mate. Suppressing storage after encountering a
draw does not protect the reverse direction: that history-free bound could still
be reused before the later search visits its drawing continuation.

For score reuse, Orient combines the position hash, the move-count clock, and a
fingerprint of the known reversible history. The fingerprint sums independently
mixed position keys, including the current position. A pawn move or capture resets
it; every other real move adds its child key. This multiset retains the occurrence
counts needed by future repetition checks. Position keys include side to move.
Order within the reversible suffix cannot change those counts before a later
irreversible reset. Unknown history preceding a loaded FEN is not invented.

Debug builds compare the incremental fingerprint against full recomputation at
real child nodes. Synthetic null branches neither probe nor store transposition
scores; their synthetic moves are not added to legal repetition history. Actual
draw checks precede table probes, and checkmate takes precedence over move-count
draws. As with position hashing, finite fingerprints retain a probabilistic
collision risk. Conservative context separation can reduce transposition reuse;
future speed changes must preserve history-safe score bounds.

`Hash Move Hints` is a separate experimental option, disabled by default. Its
board-keyed table stores only a suggested move and replacement metadata. A hint
can rank a matching legal move ahead of other moves; it carries no evaluation,
depth bound or mate claim and cannot terminate search. History-qualified score
entries remain the sole cache used for cutoffs. Synthetic null branches neither
probe nor store hints. Restricted roots do not publish their subset's preferred
move as an unrestricted hint. Full legal lists reject stale or malformed hints.

The score table receives three quarters of the requested Hash allocation and
the hint table one quarter, rounded down to complete power-of-two arrays. With
the current x86-64 entry layout, this preserves the old active score capacity at
power-of-two MiB settings, including the development 64 MiB and final 256 MiB.
Other settings may trade score entries for hint entries. Both owned vector
capacities fit within the advertised budget. Resizing allocates fresh arrays,
releasing the old allocation: the previous use of `vector::assign` retained a
larger allocation after shrinking, although its active table mask was correct.
The preserved 64-to-1 MiB reproducer fails before and passes after the repair.

Tests transpose two legal move orders with different repetition histories,
verify that only their move hints are shared, reject an illegal hint, and clear
hints on resize and Clear Hash. Forced repetition escapes pass with hints
enabled, and exact fixed-depth scores agree with reference classical/neural
searches. Hints remain off pending speed and two-stage strength measurements;
lower search work on a fixture alone would not establish an Elo gain.

Checkpoints 001–004 predate this repair. An independent public-API regression
shows a warmed history-free bound hiding a forced repetition draw in those builds.
The regression now requires both warm and fresh searches to find that draw.
Before/after inputs, binaries, outputs and hashes are preserved in
`artifacts/investigations/tt-history-001/public-api/`. The stopped Null Move test
using the defective baseline is historical evidence and establishes no gain.

## Other score boundaries

Mate scores are adjusted by search ply when stored and retrieved. Static scores
stay outside the mate band. A root restricted by `searchmoves` does not store a
score for its incomplete legal move set. Stalemates, in-check quiescence,
promotions, repetition and move-count draws have explicit regression coverage.
Stopping preserves a completed iteration or a legal fallback move.

Timed searches use an optional request timestamp, supplied by UCI before worker
handoff. Position-command processing and search setup consume that same budget;
direct fixed-depth/node callers leave the timestamp empty. Hard deadlines are
checked every 64 nodes. The default Move Overhead is 50 ms. A controlled 35 ms
pre-dispatch pause with a 120 ms clock exceeded the old reserve (about 136 ms
total) and stayed within the new reserve (about 106 ms). This is a bounded local
test, not a guarantee against arbitrary process suspension. The original failed
positions, timings and unconfirmed historical clock anomaly are retained under
`artifacts/investigations/time-pairs-001/`.

Futility pruning also checks the best searched score before skipping a quiet
move. If every searched continuation loses by mate, the remaining quiet moves
must still be searched: a static margin cannot prove a mate-distance bound for
an unsearched escape. The dedicated narrow-window regression primes a genuine
child mate in the table, verifies the alternative escape by legal-move
enumeration, and compares selective and reference scores. The original failure
and corrected output are retained in
`artifacts/investigations/futility-mate-001/`. Futility remains disabled pending
separate development and confirmation matches.

Correctness tests establish these invariants; playing-strength claims require
separate frozen match evidence. See [benchmarking](benchmarking.md).
