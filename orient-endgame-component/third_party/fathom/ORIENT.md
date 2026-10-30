# Orient's local Fathom fork

Upstream: https://github.com/jdart1/Fathom at commit
`c9c6fef0dddc05d2e242c183acf5833149ab676d` (24 December 2025).
The upstream MIT licence is retained. `UPSTREAM.json` pins the original source
archive and individual upstream files by SHA-256. `FORK.json` records local
source changes and their hashes.

Orient's adaptation, safety boundary and optional WDL cache live in its adapter;
Orient's search, evaluation and primary legal-move generator remain independent.
The reader has the Stockfish/Cfish probing-code ancestry disclosed in upstream's
README. It is attributed third-party infrastructure, not claimed original code.

An untouched full upstream source copy is retained in the
`external/fathom-upstream` directory for differential builds. Further fork edits
must record their purpose and preserve the upstream comparison baseline.

## Local source delta: recoverable mapping failures

`src/tbprobe.c`: propagate a failed memory mapping to the existing probe-failure
path instead of calling `exit(EXIT_FAILURE)`. File descriptors are closed once
by the caller, including after a failed `fstat`. On Windows a mapping handle is
closed when `MapViewOfFile` fails. This lets Orient continue ordinary search
when a table cannot be mapped; successful lookup logic and formats are unchanged.

The unchanged reference retains upstream behavior. Comparison tests cover
successful WDL/DTZ probes; fault injection separately covers the failure path.

## Local source delta: exact prefix-length hints

Experiment 003 adds a 256-byte table inside each existing `PairsData` allocation.
For each eight-bit code prefix, setup evaluates the original scalar Huffman
length rule at both interval endpoints. It stores a length only when they agree;
ambiguous intervals retain the unchanged scalar loop. Symbol selection, bit
refilling, grammar expansion and disk format remain unchanged. Constant pairs
return before consulting the new bytes. Existing allocation/free ownership and
the mapping-failure fix are preserved.

`ORIENT_FATHOM_PREFIX_LENGTH` defaults to ON in Orient after passing exactness and
performance gates against frozen 015. Its source-level default is OFF for other
clients. `prefix-length.patch` applies after `mapping-failure.patch`; the current
source digest is recorded in `FORK.json`. The 32-bit decoder forcing macro is
test-only; production builds retain the upstream platform selection.

The verified five-piece WDL/DTZ collection has at most 984 pair headers, bounding
additional header storage at 251,904 bytes (246 KiB), before allocator rounding.
Constant headers still grow by 256 bytes; unsplit or unloaded tables can reduce
actual usage. This bound does not describe arbitrary larger/DTM collections or
whole-process RSS. No new allocation calls or unbounded cache are introduced.

See [reader experiment 003](../../docs/endgame-reader-optimization-003.md) for
the interval proof, scalar-reference tests, unchanged-upstream comparisons,
paired measurements and limits. The scalar decoder reference used by tests is
copied from this pinned Fathom revision and covered by the retained attribution
and licence; it is excluded from the production reader.

## Optional catalogue and memory diagnostics: experiment 005

`ORIENT_FATHOM_FIVE_PIECE_CATALOG` allocates 84 pawnless and 61 pawn entries and
stops discovery after five pieces. Encoding arrays remain seven elements, the
material hash remains 4,096 slots, and decoder/prefix/mapping behavior is retained.
WDL, DTM and DTZ discovery within supported classes is preserved. Capacity
violations roll back initialization and return unavailable.

The option defaults to OFF: experiment 005 saved 1,966,592 requested allocation
bytes and reduced startup time, but failed the five-percent query/search
regression gate. No new candidate was frozen; Orient 016 remains retained.
`five-piece-catalogue.patch` applies after the retained prefix-length patch and
includes the diagnostic header.

`ORIENT_FATHOM_DIAGNOSTICS` also defaults to OFF. It tracks requested catalogue,
path and decoding payload, opens and mappings. Fixed diagnostic ledgers are
excluded from those payload totals. The static counter covers known mutable
control/hash storage, not all ELF/attack/index tables. Diagnostic snapshots are
serialized by the caller; no instrumentation enters acceptance/normal builds.
Adapter destruction still retains the global reader; explicit reader teardown
releases its payload/mappings. This experiment changes no table format, UCI
option, chess-history policy, training configuration or provider ownership.

See [experiment 005](../../docs/endgame-reader-memory-005.md) for all positive and
negative measurements, exactness checks, teardown evidence and the decision.

## Retained adaptive catalogue: investigation 007

`ORIENT_FATHOM_DYNAMIC_CATALOG` is ON in the retained CMake build after 007.
It stages discovered canonical WDL names at initialization, allocates exact
pawnless/pawn counts with unchanged native entry layouts, and registers those
names in original order. Successful directory listings bound the material scan;
ASCII case is folded conservatively on every platform. Failed listings restore
full discovery. Larger material filenames retain the original six/seven-piece
loops; placeholders test discovery only. Runtime WDL cache and provider lifetime
are unchanged. Direct source clients retain the OFF fallback unless they define
this macro, and C compilation retains full discovery with exact-sized allocation.
The old fixed-catalogue and adaptive options are mutually exclusive.

The accepted local campaign saves 1,966,592 requested bytes at initialization/full
sweep, improves startup, and passes every unchanged five-percent regression gate.
Allocation/listing failure, partial initialization, reinitialization and teardown
are covered. This does not harden inherited parsing against arbitrary corrupt
metadata, impose a whole-process RSS limit, or certify larger-table probing.
`adaptive-catalogue.patch` applies to the preserved pre-007 reader after the older
patches. `FORK.json` pins the current source digest. See
[improvements 007](../../docs/endgame-improvements-007.md) for all results/limits.

## Pre-publication review: disabled-reader state

Empty-path initialization now clears material hash pointers, discovery counts
and all reported/internal cardinalities before returning. `tb_free()` disables
the reader through this same path before releasing catalogue storage. Previously
the hash retained pointers to that released storage, so a direct reader probe
after teardown could access freed memory. Both empty sentinels and probes after
teardown are covered by the adaptive-catalogue regression; fixed-catalogue tests
also verify that no hash pointers or cardinalities survive. Normal loaded-table
probing, accepted catalogue sizing and decoder logic are unchanged.

`teardown-state.patch` applies after `adaptive-catalogue.patch`; `FORK.json`
records the new source digest. Historical investigation hashes remain preserved.

The direct-reader path-list parser also skips the terminal NUL when counting
directories. A trailing separator previously created a phantom directory and
caused an out-of-bounds read while locating that component. Leading, repeated
and trailing separators and separator-only lists are covered by the adaptive
regression. The engine adapter continues to accept a single directory.
`path-list.patch` applies after `teardown-state.patch`.
