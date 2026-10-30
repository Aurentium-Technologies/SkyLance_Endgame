# Investigation 006: preregistered exact-five-piece query comparison

Authorized 29 October 2026 (New Zealand date). This protocol is written before
accepted performance measurements. The final machine-readable freeze binds this
document, source/client/build hashes, corpus, dataset and correctness proof.

Orient is the current retained 016 behavior: prefix ON; cache zero; catalogue,
diagnostics, compact cache, root reuse and profiling OFF. No engine optimization,
history-policy change, games, training, larger tables or second host is included.
Preserve all original packaged evidence. External readers remain separate clients.

## Fixed roster

| ID | Repository | Commit |
|---|---|---|
| orient | frozen local current source | source archive/hash manifest |
| fathom | jdart1/Fathom | c9c6fef0dddc05d2e242c183acf5833149ab676d |
| pyrrhic_c | AndyGrant/Pyrrhic | 0613a390ca71dc991f387a1d441aad38b3731331 |
| shakmaty | niklasf/shakmaty | eb36a609da25b7f76e1ff94bbf1af7e0be53d990 |
| pyrrhic_rs | starius/pyrrhic-rs | 3801b3e6c48311f7834c11e7652e7b3d65863161 |
| stockfish | official-stockfish/Stockfish | ff7cee4244ec96ea488c402669e3674c0574dce6 |

Primary backend mmap, one query thread/process; GNU 13.3.0 and Rust 1.97.0,
release O3/native target, no LTO/PGO/instrumentation/result cache. Existing public
validation and locks stay enabled. Maximum three concurrent build jobs. A shared
compute lease excludes overlapping project experiments during correctness/timing.
Record CPU, load, available memory, accessible temperatures/frequencies and affinity;
pin timed children to the lowest numbered permitted logical CPU. No governor,
system cache, host permissions or privileged settings are changed.

## Contracts and fairness

The exact normalized contracts are those of comparison 004: five-valued WDL
after zeroing; signed nominal DTZ without move selection; and root WDL/DTZ plus
every legal alternative's nominal WDL and unsigned DTZ. Root/dtz eligibility is
no castling, at most five pieces, halfmove below 100. Raw WDL requires halfmove
zero. Terminal root/primitive-DTZ classifications normalize mate/stalemate with
DTZ magnitude zero. Earlier repetition history is outside this FEN contract.

Fathom/Pyrrhic DTZ uses measurement-only internal bridges, with one reader copy
per binary and vendor algorithms unchanged. Complete roots retain each reader's
best available correct path. Stockfish reconstructs complete values by legal-child
probes because native root ranking discards those values; native ranked-root work
is a separately labelled diagnostic. C and Rust Pyrrhic attack-hook configurations
and their attribution are pinned; no slow cross-language attack FFI is introduced.

Native parsing, input allocation and terminal preclassification precede timing.
Complete roots include legal generation, conversion/validation and canonical
sorting. Per-query latency excludes result consumption; aggregate wall time
includes it consistently. Printing, sidecar writes and percentile sorting occur
after timing. Keep original-order u64 little-endian nanosecond sidecars and report
per-material distributions. These are query stacks, not pure decoder cycles.

## Corpus and correctness

Seed 2026102906. Generate a deterministic candidate pool of 300 roots per five-
piece material class, 150 per side. Select the first 50 mutually parser-accepted
nonterminal candidates per side/class, yielding exactly 11,000 roots across all
110 classes. Exclude board/side/castling/en-passant keys present in previous
benchmark corpora. Preserve every rejected candidate and its reason. Selection
uses parser/structural acceptance only, never values or timings. The corpus is
frozen before correctness values are examined. Synthetic reachability is unproved.

All 290 publisher-verified local tables remain available for captured children.
Require exact common-domain results on the new corpus and archived shared-valid
correctness fixtures; preserve and explain any semantic incompatibility. Add
specials for en passant, promotion/underpromotion, captures, mate/stalemate,
castling rejection and halfmoves 98,99,100,101. No blanket DTZ tolerance. Rounded
metadata and native recommendation tie-break differences are separately reported.
An incompatible/unsupported contract cannot earn a superiority claim. Do not
relax guards or drop mismatching positions to make values agree.

Before acceptance timing, the correctness report binds exact binary, fixture and
dataset hashes. Test stale inputs, corpus overlap, missing/duplicate samples,
wrong query counts, enabled cache/instrumentation, changed result hashes,
incomplete campaigns, ordering balance and statistical win/loss/inconclusive cases.

## Fixed measurements and statistics

30 blocks, six variants, three operations = 540 samples; 18 separate warmups.
WDL repeats20, DTZ10, complete-root3. Fresh process per sample, OS-cache-warm
first pass separate from repeated probes. A six-treatment balanced Williams design
([0,1,5,2,4,3] modulo six, with row permutations fixed by the seed) supplies five
cycles; operation order rotates through three orders. Each block uses one seeded
corpus permutation shared by every variant/operation. First/repeated hash equality
is checked within that block and operation, because order changes between blocks.

For each of five competitors and three operations, compute the geometric mean
paired Orient/competitor wall-time ratio and p95 ratio, using whole blocks as the
sampling unit. Bootstrap 100,000 whole-block resamples, seed2026102906, sharing the
same draws across all metrics. Percentile upper bounds use 1-0.05/30, with
Bonferroni adjustment across 15 speed and15 tail gates: approximate 95% family-wise
confidence, conditional on this workload and host. Also publish lower bounds,
raw ratios, per-class breakdowns and distributions.

A supported win requires correctness/provenance, all30 blocks, wall upper<0.95
and p95 upper<1.05. Clearly slower means wall lower>1; other cases are inconclusive
or a tail-gate failure. A roster-wide superiority claim requires all15 wins.
Startup, first pass, CPU and memory are descriptive, not hidden ranking weights.
RSS includes native fixtures/mapped pages; it is not reader allocation or page cache.
Startup means table setup after native board/attack preparation, not complete
process initialization. After the primary campaign, collect five descriptive
samples per Shakmaty-pread operation and five native Stockfish ranked-root samples
(three corpus repetitions). These tasks are excluded from primary statistics.
The family-wise coverage statement applies to the 30 upper success gates;
published lower bounds are not a joint two-sided 95% guarantee.

Preserve every unfavourable sample. No outcome-dependent stopping or extra blocks.
An infrastructure failure aborts that identified campaign; retain its partial data
and reason. Repairs require a newly identified run with unchanged decision rules.
Do not call successful tool execution a performance win. No production candidate
is adopted, regardless of the result. The known history-sensitive draw-loss remains
open and prevents any claim of perfect endgame play.
