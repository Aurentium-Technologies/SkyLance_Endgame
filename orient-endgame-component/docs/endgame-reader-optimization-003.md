# Five-piece reader optimization 003

This historical report names supporting files from the wider local research archive. Available public records and separate downloads are listed in the [evidence index](../../evidence/README.md); local-only paths below are not GitHub download links.


Date: 28 October 2026, New Zealand local date.

The exact prefix-length decoder accelerator passes the 20% research target and
the existing adoption gates. In the final five-pair native confirmation against
frozen 015, complete adapter probes take **34.60% less elapsed time** and complete
covered root searches take **31.04% less time**. Results remain identical. These are
workload measurements, not a whole-engine speedup or an Elo claim.

## What changes

The reader repeatedly finds Huffman code lengths while accessing the existing
Syzygy files. A new 256-byte hint table per codebook replaces many scalar
threshold walks with an exact lookup. For each eight-bit prefix, initialization
evaluates the original rule at both endpoints. If the resulting lengths agree,
every intervening code has that length. Otherwise the original scalar loop runs.

Symbol selection, bit refills and compressed-symbol expansion retain their
original calculations. Files remain byte-for-byte unchanged. The added bytes
share each existing allocation and `free`; constant tables return before reading
them. There are no extra allocation calls or unbounded result caches.

For the verified 145-class collection, at most 984 pair headers need at most
**251,904 extra bytes (246 KiB)** of structure storage. Measured glibc live heap
after probing increases by 249,440 bytes in each isolated paired sample.
Allocator rounding and whole-process RSS are separate measurements. The bound
applies to this WDL/DTZ collection, not arbitrary larger or DTM collections.

The local Fathom source remains pinned to upstream
`c9c6fef0dddc05d2e242c183acf5833149ab676d`, with MIT attribution, the existing
mapping-failure repair and the new delta recorded in
[`FORK.json`](../third_party/fathom/FORK.json). The prefix patch is separate from
the preserved mapping-failure patch. `ORIENT_FATHOM_PREFIX_LENGTH` enables the
retained reader optimization. Adapter value caching stays at zero; the rejected
compact-cache and root-list-reuse options remain OFF.

No Orient evaluation, primary move generation, search policy, repetition guard,
UCI option, training configuration or table format changes. In particular, the
history-fallback limitation from [playing diagnostic 001](endgame-playing-001-2026-10-28.md)
remains a separate integration task.

## Protocol and rejected experiments

The protocol (local archive: `../artifacts/investigations/tablebases-003/PROTOCOL.md`) fixes the
20% complete-probe time-reduction research target and the existing 1.05x minimum
whole-path throughput adoption gate. Both complete probes and complete root
searches must pass; reader/root p95, hot-root probes, distinct WDL and descendant
search time ratios must not exceed 1.05. Preserve every result and trial.

The baseline is the immutable 015 source archive, checked against its recorded
hashes and rebuilt with only the common measurement harness. Separate source
trees isolate three first-round variants. All pass the 12,010-case differential
but fail performance adoption in 20 retained trials:

| First-round variant | Complete probe time change | Complete root-search time change | Decision |
| --- | ---: | ---: | --- |
| Skip absent sliding attacks | +4.43% | +3.15% | Reject |
| Carry exact material signatures through moves | +8.41% | +7.09% | Reject |
| Combine those changes | +11.29% | +5.42% | Reject |

These results apply to the measured workloads. Added branches or copied state
can cost more than the arithmetic they avoid; removing operations does not prove
a useful speedup. No unfavorable result was discarded or rerun to change its
decision.

The prefix accelerator is a materially different candidate. Its
separate pre-timing protocol (local archive: `../artifacts/investigations/tablebases-003/PROTOCOL-prefix.md`)
freezes another five paired trials, alternating baseline/candidate order, with
the same corpora and gates. Each workload repeats three times. OS caches are
prewarmed, processes start fresh, no whole-root result is cached, and the project
compute lease excludes other heavy experiments. Native Release builds use the
same compiler options and no profiling. Instrumented build definitions are
rejected from both CMake caches and compile commands; binaries, fixtures,
controller sources and dataset are reverified after the run.

The workload includes 10,005 distinct covered positions across 145 material
classes, a 145-position repeated hot set, 48 six-piece depth-four searches that
probe covered descendants, and complete root searches across the covered corpus.
The first adapter sweep, including lazy table initialization, is measured
separately from steady-state sweeps. Cache size stays zero in acceptance trials.

## Isolated prefix acceptance measurements

Ratios below are paired geometric means, candidate time divided by baseline time:

| Workload | Time ratio | Interpretation |
| --- | ---: | --- |
| Complete distinct adapter probes | 0.650057 | 34.99% less elapsed time; 1.5383x throughput |
| CPU time for those probes | 0.649646 | 35.04% less CPU time |
| Complete-probe p95 | 0.601083 | 39.89% lower |
| Repeated hot-root probes | 0.601204 | 39.88% less time |
| Complete covered root searches | 0.685325 | 31.47% less time; 1.4592x throughput |
| Complete root-search p95 | 0.628683 | 37.13% lower |
| Distinct WDL probes | 0.930660 | Passes regression gate |
| Six-piece descendant searches | 0.965420 | Passes regression gate |
| First complete adapter sweep | 0.687400 | Includes lazy initialization; 31.26% less time |

The reader and covered-root gains occur in every pair. Descendant-search results
are mixed: four pairs take 0.32–2.59% longer and one takes 19.91% less time.
Their aggregate passes the regression gate, but does not establish reliable
descendant-search acceleration. Reader constructor time is about 3.3 ms and
excludes lazy codebook setup; its 0.982945 ratio is not claimed as a startup gain.

All 30 trials across both rounds share identical complete-probe and search
result hashes. Complete-probe hashes include WDL, DTZ, recommendation and ordered
legal alternatives. Search hashes include moves, scores, nodes and tablebase
hits. The raw trials (local archive: `../artifacts/investigations/tablebases-003/measurements-prefix/result.json`)
and quantitative summary (local archive: `../artifacts/investigations/tablebases-003/acceptance-summary.json`)
retain values, configuration, fixtures, hardware and binary hashes.

Peak RSS includes fixtures, search storage and mapped file pages. The isolated
reader samples increase by 212–712 KiB; complete-harness samples increase by
252–616 KiB. Neither RSS delta is bounded by the smaller header-storage bound.
No privileged cache flushing, perf-setting changes or hardware changes were used.

## Profiling and correctness

The profiling diagnostic (local archive: `../artifacts/investigations/tablebases-003/profiling/README.md`)
adds optional sampled application scopes inside an isolated reader. Compiling
it out reproduces the baseline benchmark and Fathom object byte-for-byte.
All twelve diagnostic runs preserve results. Tiny-function timer overhead
substantially contaminates attack timing, so sampled shares are not interpreted
as exact pure-work costs. Counts and uninstrumented trials drive the decision.
Profiler code remains isolated research infrastructure, excluded from production.

Both the native 64-bit decoder and the existing 32-bit decoding branch, exercised
on this 64-bit host, pass 792,164 length checks and 65,536 full scalar-reference
decoder comparisons each. Cases include interval endpoints, threshold neighbors,
random codes, ambiguous intervals, constant tables and minimum lengths 1, 3 and
5. The independent scalar routine is preserved test-only code from frozen 015.
The 32-bit test is not a claim of execution on a 32-bit operating system.

The isolated candidate matches unchanged upstream on all 10,005 material and
2,005 special cases, including DTZ, suggestion and the complete alternatives.
The special set retains near-limit clocks, en passant, promotions,
underpromotions, terminal positions and castling rejection. Measurement labels
and game outcomes are excluded from training.

## Integration and frozen delivery

The integrated source receives another fresh five-pair confirmation, preserving
the isolated acceptance and its baseline. All ten final samples pass exact hash
checks and the same gates. Final paired time ratios are:

| Integrated measurement | Ratio |
| --- | ---: |
| Complete adapter probes / CPU time | 0.653986 / 0.654085 |
| Adapter p95 / hot-root probes | 0.604473 / 0.613235 |
| Complete covered root searches / p95 | 0.689613 / 0.632211 |
| Distinct WDL / descendant searches | 0.968091 / 0.952548 |

All 40 acceptance samples across the three sets preserve the compared results.
Final reader throughput is 1.5291x and covered-root throughput 1.4501x. These are
not percentages of time saved. The integrated heap difference is 249,472 bytes
per sample; this includes minor adapter-layout differences from the 015 source.
The structural prefix bound remains 251,904 bytes. Constructor timing varies;
no constructor/startup improvement is claimed.

The full release/native/debug/sanitizer suites pass **116 CTest groups**, zero
failures or top-level skips: 30 release, 30 native, 28 debug and 28 sanitize.
Debug/sanitize retain the existing two extended-perft exclusions. Leak detection
is disabled (`detect_leaks=0`); address/undefined-behaviour checks remain enabled.
Both decoder widths and the nine adoption/provenance guard cases run in each.
The final upstream differential repeats all 12,010 cases at cache 0/1/4/16 MiB,
with all output fields and alternatives identical.

With probing disabled, frozen 015 and both final release/native builds preserve
the same CLI depth-six moves, scores and node counts. Eighteen additional UCI
searches preserve them at depths four/five with a loaded path and probe limit
zero, including halfmove 98 and actual repetition history. Every hit count is
zero. Existing UCI stop, finite/infinite analysis, missing files, cache/path
changes and history regressions pass in the full suite.

The new 016 checkpoint (local archive: `../artifacts/checkpoints/orient-016-reader-prefix/checkpoint.json`)
pins native binary SHA-256
`46304f7b2ef9d6b4f36b2a0fa0012e8c0cbf77a2a172f054b0cac4c4b6b3b429`,
source including reader/licence/patches/tests, build settings and the verified
dataset manifest. Effective build: prefix ON; compact cache, root-list reuse and
profiling OFF. Runtime coverage remains five pieces and cache 0.
A separate ignored offline profile targets 016 using a placeholder account and
an unused token environment variable. Offline preflight verifies hashes, all
table files, a legal probed move with nonzero hits and bounded ordinary search;
it reads no token and starts no connection or game. Existing profiles are not
redirected to the new candidate.

Retained evidence:

- Final five-pair confirmation (local archive: `../artifacts/investigations/tablebases-003/measurements-integrated/result.json`)
- Full build/test verification (local archive: `../artifacts/investigations/tablebases-003/verification-summary.md`)
- Final upstream comparison (local archive: `../artifacts/investigations/tablebases-003/final-comparison/result.json`)
- Disabled-tablebase equality (local archive: `../artifacts/investigations/tablebases-003/disabled/result.json`)
- Offline profile preflight (local archive: `../artifacts/investigations/tablebases-003/offline-preflight-016.json`)
- Final provenance and effective settings (local archive: `../artifacts/investigations/tablebases-003/delivery.json`)

The earlier 015 candidate and all prior profiles/experiments remain recoverable.
All table files are unchanged. No online game, rating campaign or training-policy
change belongs to this work. Timings apply to the measured Linux host and
workloads; Windows and an actual 32-bit operating system were not executed.
