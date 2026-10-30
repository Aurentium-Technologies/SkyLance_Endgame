# Investigation 008: post-review source confirmation

Apply the unchanged 007 workloads, five AB/BA pairs and numerical gates
below to the frozen pre-007 baseline and explicitly selected current
candidate. Preserve every sample and failed run. This is a new run, not
a replacement for historical 007 evidence or a competitor/Elo claim.
The base commit identifies the checkout; per-file source hashes bind the
actual compiled snapshot, including any intentional uncommitted files.

# Investigation 007: safe retained-reader improvements

This is a new before/after implementation experiment on this machine, not an
extension of campaign 006. Preserve investigations 001-006, original package
manifest and baseline source. No engine training, games or external engine code
is added. The fixed drawing-root history change has a separate rules proof and
full-history regression; it makes no Elo or complete history-aware-play claim.

## Development boundary

Known 004 continuity positions may guide development. The adapter-generation
fast path and short-symbol decoder are separate candidates; preserve their
negative results. Only the adaptive catalogue (with original entry layout,
encoding and exact native probes) proceeds to memory/startup acceptance. The
production decoder, prefix accelerator and result-cache-zero configuration stay
unchanged. No catalogue data or filesystem discovery is cached across provider
activations. Directory listing is only a conservative upper bound; failed
listings use original full discovery, ASCII case is folded on all platforms,
and the original file existence/size checks register actual tables.

## Correctness and data

Verify all 290 table files against the saved SHA-256 manifest. Preserve 3/4-piece
files for captures. Compare exact WDL, signed nominal DTZ, root values, native
recommendations and ordered alternatives, with no tolerance. Re-run 12,010
upstream cases at result-cache sizes 0/1/4/16 MiB, and 21,963 archived shared-valid
cases plus 11,000 primary 006 roots and 11,000 fresh 007 roots against the saved
pre-change baseline. Retain parser rejections and all differences. Complete
correctness before timing; bind evidence to each binary and corpus digest.

Fresh 007 uses seed 2026103007, 100 roots per 110 exact-five-piece material
classes, 50 per side, halfmove zero, and excludes all previously collected board,
side, castling and en-passant keys. Freeze before query values or timing are
inspected. Static validity and independent parser acceptance do not establish
historical reachability. Fixtures include en-passant, promotions, captures into
smaller tables, terminals, castling rejection and clock boundaries. New dynamic
unit cases cover empty/partial/full/multiple/missing directories, case-folded
names, listing failure fallback, resizing/reuse, staging and both allocation
failures, balanced teardown and recovery. Fake six/seven-piece filenames test
discovery only, not real larger-table probes or corrupt-file robustness.

## Fixed acceptance campaign

Use the preserved baseline versus the adaptive-catalogue + history-fix candidate.
Use GCC 13.3.0, C++20 Release -O3 -DNDEBUG -march=native, no LTO/PGO, one query
thread, result cache zero, prefix ON, fixed catalogue/compact cache/root reuse/
profiling/diagnostics/short-symbol experiments OFF in timed executables. Memory
counters use separate diagnostic executables. Compiler definitions in the native
reader and measurement-only DTZ shim must match.

Exactly five paired trials: AB, BA, AB, BA, AB. Each invocation is a fresh process;
only one timed child at a time under the existing shared compute lease. Pin
controller and children to one permitted logical CPU recorded in config. No
builds while timing. Record host load, memory and accessible frequency/temperature
without changing host settings. Warm local mmap is primary; parse/allocation,
constructor, first pass and repeated query costs remain separate. JSON printing
and latency sorting are outside the query timer. Complete-root includes legal
generation and result normalization. Position order is the frozen corpus order
for both variants; operations use the same fixed WDL, DTZ, complete-root order.

For each trial/variant, measure WDL20, DTZ10, complete-root3 on each 11,000-root
corpus; depth4 descendant searches on the unchanged 48 six-piece fixtures and
complete root searches on each primary corpus (3 repeats); and 145 hot roots
(96 repeats). Save 20 fresh reader-constructor + UCI configuration/first-root
samples per trial/variant. Precede trials with declared warmups and separate
memory runs on both corpora. Retain every raw result and interrupted/invalid run;
repairs require a new run identifier. Do not extend trials to pass.

Adoption uses geometric means of paired candidate/baseline time ratios, with
whole trial as the unit, and the existing investigation005 gates unchanged:

- At least 1 MiB less requested live reader allocation after initialization AND
  full sweep on BOTH corpora.
- Constructor and configured-readiness ratios at most 0.80.
- Setup-first-root, primary WDL/DTZ/root wall, first-pass and p95, hot wall,
  first-pass and p95, descendant-search elapsed, root-search elapsed and root-p95
  ratios at most 1.05.
- All correctness, provenance, cache-zero and complete-campaign checks pass.

CPU time and process peak RSS are recorded; requested reader payload, whole
process RSS, mapped table bytes and kernel page cache have separate meanings.
These five-trial gates are engineering adoption checks, not the 30-block
family-wise superiority experiment of 006. No new competitor superiority or
formal confidence claim is inferred. An independent implementation recomputes
raw-artifact completeness, exact hashes, paired ratios and decisions. Any failed
performance candidate stays unadopted, and its evidence remains available.
