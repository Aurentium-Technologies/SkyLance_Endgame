# Five-piece probe/cache experiment 002

This historical report names supporting files from the wider local research archive. Available public records and separate downloads are listed in the [evidence index](../../evidence/README.md); local-only paths below are not GitHub download links.


Date: 27 October 2026, New Zealand local date.

**Decision: retain frozen candidate 015 and the zero-cache default.** Both
optimization prototypes preserve exact results, but neither meets its declared
performance adoption gate. The prototypes, profiling tools and measurements are
retained for reproducible research; their CMake options default to **OFF**.
The existing table files and their format are unchanged.

## Implemented prototypes

The compact cache represents an exact position identity in 52 bits: both king
squares, side, en-passant state, nonking count and three canonically ordered
square/type/colour records. WDL and independent validity bits bring the payload
to 56 bits inside one eight-byte integer. It is not a shortened hash. The codec
checks its bounds, supports all five WDL values including loss zero, and compares
the complete identity on hits. Cache-zero avoids encoding; misses alone build
the larger Fathom board representation. Dataset invalidation and reader locking
are preserved.

At a configured 4 MiB, the old implementation holds 52,428 entries in 4,194,240
bytes; the compact prototype holds 524,288 entries in 4,194,304 bytes. This is
approximately **10 times the capacity at the same memory budget**, not a 90%
reduction in the allocated budget. A compact 1 MiB cache holds 131,072 entries.

The root prototype reuses Searcher's complete, unrestricted legal-move list,
then applies `searchmoves` to selection as before. The standalone reader method
remains available. Returned moves and the complete alternative set are still
validated, and an incomplete empty caller list cannot manufacture a terminal
result. Reserving the result vector once removes repeated capacity growth.
Mate, draw, repetition, cancellation and rounded-DTZ handling are unchanged.

Opt-in application instrumentation measures root legal generation, Fathom
probing, result validation, adjudication and result-vector allocation events.
Acceptance binaries have profiling disabled. Host `perf` settings were not
changed, and Fathom decoder internals were not changed.

## Baseline and protocol

The actual acceptance baseline is candidate 015's source archive, SHA-256
`da9433a5a1e65b5d0d690643a249e8f6772b1328186bbe7a5ecfb48ef76f86dd`.
Its engine/reader source hashes were verified after extraction. Only the common
new measurement harness and its target definition were overlaid for the
baseline build; the original archive and frozen binary remain intact.

Separate binaries isolate root-only, compact-only and combined changes. An
instrumented current-source legacy configuration supplies diagnostic phase
measurements; it is explicitly not the frozen acceptance baseline. Build
commands, flags and executable hashes are preserved in
variant-builds.json (local archive: `../artifacts/investigations/tablebases-002/variant-builds.json`).

The acceptance run uses five paired trials with rotated order across 13 cases:
baseline caches 0/1/4/16 MiB, root-only 0, compact-only 0/1/4/16, and combined
0/1/4/16. Every sample repeats the same workloads three times: 10,005 WDL
positions, 48 six-piece depth-four searches probing covered descendants, and
10,005 complete root searches on covered positions. Fixture hashes match
experiment 001. OS caches are prewarmed, processes/value caches are fresh,
whole-root results are not cached, and timing uses exclusive compute ownership.
Startup, RSS, capacity, latency percentiles and all raw trial values are saved.

All 65 acceptance cases match the same lookup, descendant-search and root-search
result hashes. Each sample has 5,724 root search nodes, 29,727 root tablebase
hits and three ordinary-search fallbacks across the three repetitions, identically
for every implementation/cache setting. Counts include the existing conservative
draw and DTZ-boundary handling.

## Profiling and adoption result

In the instrumented legacy diagnostic, Fathom probing consumes approximately
**94.45%** of measured root workload time. Initial/duplicate legal generation
accounts for 1.61%, result validation 0.74%, and adjudication 1.60%; remaining
time is outside those measured phases. Instrumentation is for attribution only.

The prototype reduces counted result-vector allocations from 135,468 to 29,277
over 29,277 reader calls. This counter excludes other allocations such as the
old copied position's history. Legal-generation and validation work also shrink,
but they occupy a small part of the complete root path.

| Independent candidate | Paired geometric-mean result | Declared gate | Decision |
| --- | --- | --- | --- |
| Root reuse, cache 0 | Root throughput 1.000934x; root p95 time 1.004046x; descendant search time 0.942278x | Root throughput at least 1.05x, p95/descendant regressions at most 1.05x | Reject: root throughput gain is about 0.09% |
| Compact cache, 1 MiB versus old 1 MiB | Descendant search time 1.051653x | At most 1.05x at every matching memory setting | Reject: measured time increases 5.17% |
| Compact cache, 4 MiB versus old 4 MiB | Descendant search time 1.008539x | At most 1.05x | Pass at this size |
| Compact cache, 16 MiB versus old 16 MiB | Descendant search time 0.998235x | At most 1.05x | Pass at this size |

The compact prototype must pass **all** matched-memory settings; the 1 MiB
failure prevents adoption. Combined cache-zero changes also fail the root gate
(0.953368x root throughput and 1.058779x p95 time). There is therefore no adopted
family from which to choose a new default cache: keep zero and candidate 015.

Individual trials vary materially. These are workload-specific measurements,
not proof that compact encoding is always slower or that the small observed
differences generalize. The agreed five-pair results are retained without
selecting a favorable rerun or changing thresholds after seeing the outcomes.
The unrelated descendant-search gain in the root-only binary does not satisfy
the root-throughput criterion.

Protocol, all 65 trials, profiles and calculated decision (local archive: `../artifacts/investigations/tablebases-002/measurements/result.json`).

## Correctness, defaults and delivery

The codec passes 10,000 unique round trips, evenly covering two through five
pieces, plus targeted square/type/colour/side/EP distinctions, maximum payload,
loss-zero validity, invalid bounds and forced hash collisions. Integration tests
cover arbitrary 1/3/4/16 MiB indexing, cache clearing, dataset switching, both EP
directions, promotions, full-list reuse, incomplete-list rejection and direct
legal generation combined with restricted root moves.

The full prototype suite passes release (24 groups), native (24), debug (22) and
address/undefined-behavior sanitizer (22): **92 CTest groups passed**. Extended
perft runs in release/native per the existing presets. Leak detection is disabled
for the sanitizer run (`detect_leaks=0`). The upstream differential again matches
10,005 material cases plus 2,005 special cases at cache sizes 0, 1, 4 and 16 MiB.

Reproduction options are `ORIENT_COMPACT_TABLEBASE_CACHE`,
`ORIENT_REUSE_ROOT_LEGAL` and `ORIENT_TABLEBASE_PROFILING`; all default to OFF.
Explicit experimental builds and their flags are recorded separately. Standard
build caches are reset to those defaults and receive focused endgame/UCI checks
in all four presets. Disabled-tablebase fixed-depth results are compared with
the actual frozen 015 binary. The previous offline profile is reverified;
no new candidate/profile is promoted because no optimization passed adoption.

Evidence:

- Prototype verification (local archive: `../artifacts/investigations/tablebases-002/prototype-verification.json`) and per-preset build/test logs.
- 12,010-case upstream comparison (local archive: `../artifacts/investigations/tablebases-002/comparison/result.json`).
- Restored-default checks (local archive: `../artifacts/investigations/tablebases-002/default-verification.json`).
- Disabled-search equality (local archive: `../artifacts/investigations/tablebases-002/disabled-search-equality.json`).
- Existing 015 offline preflight (local archive: `../artifacts/investigations/tablebases-002/offline-preflight-015.json`).
- Source/provenance delivery audit (local archive: `../artifacts/investigations/tablebases-002/delivery-audit.json`).

The first experiment, frozen 015 binary/source and table data are preserved.
No live game, rating campaign, training-data/weight change or file-compression
experiment was performed. Windows execution was not tested on this Linux host.
The profile identifies Fathom's internal probing as the main remaining research
target; this iteration deliberately leaves its decoder unchanged.
