# Five-piece endgame integration — 27 October 2026

Orient now supports the complete three-, four- and five-piece Syzygy collection
through an attributed local Fathom fork. The owner explicitly approved shared
solved-position data and reader infrastructure while retaining Orient's own
playing algorithm. Ordinary search, evaluation, primary legal-move generation
and the own-data neural training pipeline remain Orient implementations.

## Delivered behavior

The UCI interface exposes `SyzygyPath` (empty by default),
`SyzygyProbeLimit` (5, range 0–5), `SyzygyCache` (0 MiB, range 0–256) and
`tbhits`. The tables are local disk files; no network service is used during play.
The adapter checks every returned move against Orient's legal list. Missing
tables and unsupported positions retain ordinary search.

Root DTZ/outcome selection respects restricted root moves, the real halfmove
counter, actual mates and draws. Earlier reversible repetitions, and quiet
alternatives exactly on the rounded DTZ/rule-50 boundary, retain ordinary
history-aware search. Internal WDL shortcuts require a reset counter, no
castling rights and no synthetic null-move ancestry. Proven outcomes use
scores of ±25,000, below the mate band; a tablebase win does not invent a mate
distance. Stop/clock checks surround probes.

The optional bounded cache stores successful raw WDL values, verifies full board
identity after slot lookup, and invalidates across dataset generations. Its
memory is separate from `Hash`. The default remains zero following the declared
performance gate below. The local reader source also returns an unavailable
probe on memory-mapping failure instead of exiting, closing the associated
file/mapping handles. Eight deterministic injected failures verify that path
without descriptor leakage.

The pinned upstream revision is
`c9c6fef0dddc05d2e242c183acf5833149ab676d` from
[jdart1/Fathom](https://github.com/jdart1/Fathom). Its MIT licence, original hashes,
fork delta and patch are preserved in `third_party/fathom/`. The unmodified
upstream source is separately retained under ignored `external/fathom-upstream`
for comparison; the reference executable does not link Orient's adapter.

## Dataset and correctness evidence

All **290 files across 145 material classes**, totalling **983,957,920 bytes**
(about 984 MB), are installed under `external/tablebases/syzygy/3-4-5`. The
resumable downloader verifies publisher SHA-256 values before atomically
publishing each file. A complete-set manifest records names, sizes, sources and
hashes; the offline bot profile verifies all bytes against the pinned catalogue.

Dataset manifest SHA-256:
`7d4eae2c333da3b8b9e485e0496efc56a07b4452e2bb53e83cfa6bceb9c7a73d`.
The publisher catalogues are linked in the saved data manifest and bundled
`tools/syzygy345.json`.

The upstream differential compares **10,005 reproducible rule-validated
nonterminal positions spanning all 145 material classes**, plus **2,005
additional cases** covering halfmove counters 98/99, en passant, underpromotion,
terminal positions and castling rejection. Seed: 20261027. The uncached fork
and 4/16 MiB cache variants match unchanged upstream exactly for WDL, root
outcome, DTZ, suggested legal move and the complete alternative move set.
These fixtures/results are validation evidence, never training labels.

Existing release and native fixed-depth benchmarks with tablebases disabled
preserve the same moves, scores and **234,041 nodes** as the pre-change binaries.
The complete CTest runs pass in release (22 groups), native (22), debug (20)
and address/undefined-behavior sanitizer (20): **84 groups passed**. Extended
perft runs in release/native per existing presets. Sanitizer leak detection was
disabled (`ASAN_OPTIONS=detect_leaks=0`). Final offline bridge tests were rerun
after changing the functional preflight to a depth bound independent of live
clock overhead. The bridge suite contains 39 cases; downloader tests contain 7.

Evidence under `artifacts/investigations/tablebases-001/`:

- [Complete dataset audit](../artifacts/investigations/tablebases-001/dataset-verification.json).
- [Upstream differential and output hashes](../artifacts/investigations/tablebases-001/comparison/result.json).
- [Four-preset verification](../artifacts/investigations/tablebases-001/verification.json), build/test logs and [final bridge checks](../artifacts/investigations/tablebases-001/final-bridge-checks.json).
- [Disabled-search regression](../artifacts/investigations/tablebases-001/disabled-after.json), with the preserved `disabled-before.json`.

## Cache experiment and decision

Five paired trials rotate the order of 0, 4 and 16 MiB settings. Each uses the
same 10,005-position raw-WDL corpus and 48 independently rule-generated
six-piece positions searched to fixed depth four, probing five-piece descendants.
The latter exercise integration before the covered ending is on the board.
Each search workload returns exactly the same moves, scores and 167,889 nodes,
with 31,507 successful tablebase hits. The OS cache is prewarmed; each trial
starts a new reader/value cache. No privileged cache flush is used.

The following are geometric means across the five trials:

| Cache setting | Allocated value cache | Reader startup | Distinct WDL corpus | Repeated WDL workload | Complete search workload |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0 MiB | 0 bytes | 5.27 ms | 48.52 ms | 44.77 ms | 425.81 ms |
| 4 MiB | 4,194,240 bytes | 7.91 ms | 47.72 ms | 11.27 ms | 410.58 ms |
| 16 MiB | 16,777,200 bytes | 17.49 ms | 49.46 ms | 6.63 ms | 432.26 ms |

The 4 MiB setting measures a **1.0371× search speedup**, below the predeclared
1.05× threshold; 16 MiB measures **0.9851×**. Both preserve results, and neither
exceeds the allowed 5% distinct-lookup regression, but neither passes the full
adoption gate. **Select 0 MiB.** Faster repeated raw lookups alone do not justify
enabling the cache. Measurements vary between trials and establish no general
speed or playing-strength gain.

[Raw trials, memory readings and gate decision](../artifacts/investigations/tablebases-001/cache/result.json)
also preserve the executable and fixture hashes. The reported process RSS is
Linux whole-process memory, including mapped table pages and search storage;
the explicit cache allocation above is the bounded additional value cache.

## Frozen delivery and limits

The new [015 candidate checkpoint](../artifacts/checkpoints/orient-015-syzygy/checkpoint.json)
pins the engine, source archive including Fathom/licence, reader revision,
dataset manifest and effective five-piece/zero-cache settings. The separately
ignored `config/lichess.endgame.local.json` profile targets it. Its
[offline preflight](../artifacts/investigations/tablebases-001/offline-preflight.json)
verifies a legal KQvK move with nonzero `tbhits`, followed by the existing bounded
start-position search. No token, account API or live game is used by this check.
Existing frozen candidates and the previous live profile remain recoverable.

See [setup and configuration](endgame-tablebases.md). Self-play generation has
no tablebase provider and accepts no tablebase configuration; no training data,
labels or weights were changed. No match campaign or Elo claim is part of this
integration. Windows execution was not verified on this Linux host. Synchronous
disk probing cannot guarantee a deadline during arbitrary OS/storage stalls.
Six-piece coverage, opening books and new compression formats remain separate.

## Reader follow-up — 28 October 2026

[Reader experiment 003](endgame-reader-optimization-003.md) retains an exact
prefix-length accelerator in the local Fathom fork. Final paired confirmation
reduces complete-probe time by 34.60% and covered root-search time by 31.04%
with identical results, unchanged table files and at most 246 KiB added header
storage. The new 016 candidate passes 116 CTest groups and the full differential
at cache 0/1/4/16. Cache default stays zero, training stays tablebase-free, and
015/existing profiles remain recoverable. No Elo gain is claimed.
