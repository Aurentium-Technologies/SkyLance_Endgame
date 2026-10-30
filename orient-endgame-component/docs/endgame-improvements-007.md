# Retained endgame improvements 007

The recorded repetition-history draw-loss case is fixed. The adaptive material
catalogue is adopted after passing exact-answer, memory/startup and five-percent
regression gates. Two direct WDL speed experiments were slower and remain
unadopted; the smaller retained reader nevertheless measured faster WDL queries
in this campaign.

## What changed

Search can retain certified drawing moves at a strict WDL2 root even when earlier
positions repeated. It makes every candidate with full actual history, gives
mate priority and respects searchmoves. Decisive/cursed/blessed roots and unsafe
restricted alternatives still use ordinary history-aware search. TT keys,
null-search safeguards and repetition/rule-50 adjudication are preserved. The
recorded 36-ply transcript now chooses Ka1 or Ka2 at score 0. This fixes that known
weakness without asserting perfect history-aware play or Elo improvement.

The reader allocates its native catalogue for discovered materials (84 pawnless,
61 pawn entries here), retaining original entry layouts, encoding dimensions and
hash size. Conservative directory bounds avoid unnecessary larger-material file
opens: full local initialization uses 435 rather than 1801 attempted opens.
Listing failure retains full discovery, all filename case is conservatively
handled, and larger-material discovery is retained. Setup-only staging is on the
stack; runtime result cache remains zero. No production API changed.

## Fixed measurements

Intel Core i7-10810U, Linux x86_64, permitted logical CPU 0, GCC 13.3.0, C++20
Release with native targeting, no LTO/PGO or timing instrumentation; one timed process/thread.
Five fixed AB/BA paired trials, 60 primary reader samples, 20 search samples,
10 hot samples and 200 fresh reader/UCI startup pairs. Continuity is the frozen
006 primary corpus; the fresh holdout uses seed 2026103007, 11,000 roots, 100 per
110 five-piece classes balanced by side. Position selection preceded values and
timing; rejected candidates are preserved. Static validity does not establish
complete game reachability. Both corpora use warm local mmap and identical
position/operation order. This is a before/after engineering acceptance campaign,
not the 30-block family-wise competitor-superiority test of 006.

Startup times are geometric means of per-trial medians. Query changes are
geometric means of paired elapsed/p95 ratios. Changes are candidate/baseline
minus 1; negative means less elapsed time.

| Startup stage | Baseline | Retained candidate | Change |
|---|---:|---:|---:|
| Reader construction | 3.772 ms | 1.370 ms | -63.69% |
| Configured readiness | 6.819 ms | 4.074 ms | -40.25% |
| Configuration plus first root | 7.185 ms | 4.395 ms | -38.83% |

| Corpus | Query | Elapsed change | p95 change |
|---|---|---:|---:|
| continuity | WDL | -11.52% | -11.10% |
| continuity | DTZ | -10.42% | -10.61% |
| continuity | Complete root | +3.02% | +3.06% |
| holdout | WDL | -7.48% | -7.96% |
| holdout | DTZ | -6.11% | -6.26% |
| holdout | Complete root | -9.46% | -9.29% |

The largest gated regression was 3.06%
(continuity complete-root p95), below 5%. Continuity complete-root elapsed was
3.02% slower; heldout complete-root elapsed was 9.46% faster. Hot elapsed changed
+0.16%, with p95 -0.36%. Descendant search elapsed changed -6.48% / -1.75%,
and full root-search elapsed -2.42% / -1.79% for continuity/holdout. Every exact
query/search result hash, node count and tablebase-hit count matched. These are
observed local ratios; no new statistical confidence or competitor-ranking
claim is inferred.

## Memory scope

Requested live reader payload fell by exactly 1,966,592 bytes (1.875 MiB) after
initialization and full sweep on both corpora. Both explicit teardowns report
zero requested reader allocation and mapped bytes. Whole-process RSS below is a
separate diagnostic measurement and includes instrumentation/allocator/shared
resident table pages; it is not the adoption metric.

| Corpus/phase | Baseline reader bytes | Candidate reader bytes | Process RSS baseline / candidate |
|---|---:|---:|---:|
| continuity/after_init | 2,137,606 | 171,014 | 5.86 / 4.20 MiB |
| continuity/after_full_sweep | 4,822,206 | 2,855,614 | 804.00 / 802.29 MiB |
| holdout/after_init | 2,137,606 | 171,014 | 5.88 / 4.17 MiB |
| holdout/after_full_sweep | 4,822,206 | 2,855,614 | 812.68 / 810.93 MiB |

The 290 immutable table files still occupy 983,957,920 bytes on disk. Virtual
mappings, per-process table-page RSS/PSS, anonymous memory and allocator counters
are retained separately in the raw snapshots. Kernel page cache was not assigned
a reader-owned RAM total. This optimization does not impose a hard total-RSS cap.

## Correctness and rejected work

All 290 publisher table hashes passed before and after. The exact comparison
stored 319,972 JSON rows and 4,703,656 move records across 44 outputs, with zero
differences. It includes 12,010 upstream cases at cache 0/1/4/16 MiB, 21,963 archived
shared-valid cases and both 11,000-root primary corpora. Root recommendations and
native alternative order remain exact; no DTZ tolerance was added. Native 23/23
CTest groups and six focused ASan/UBSan groups passed, including 64/32-bit scalar
prefix checks, provider switching, cache invalidation, history and catalogue
resize/failure recovery. LeakSanitizer itself is unavailable under the execution
wrapper's ptrace; that failed attempt is preserved. See [review limits](../../evidence/tablebases-007/code-review.md).

The generation-qualified adapter experiment measured 2.22% slower WDL in its
old-data development screen and was removed from production. The short-symbol
experiment was exact but measured 3.84% slower WDL, 12.60% slower DTZ and 19.42%
slower complete roots over four development blocks. Its additional 512 bytes per
pairs header were not adopted. All negative patches, binaries, source archives
and raw results remain in the separately packaged 007 evidence archive. The native adapter and prefix decoder remain.

## Evidence, reproduction and claim

[Protocol](../../evidence/tablebases-007/protocol/PROTOCOL.md),
[raw result](../../evidence/tablebases-007/performance/acceptance-002/result.json),
[exact correctness](../../evidence/tablebases-007/verification/correctness-001/result.json),
[separate raw-artifact recomputation](../../evidence/tablebases-007/independent-recomputation.json),
[history proof](../../evidence/tablebases-007/history-guidance-proof.md),
and [reproduction package](../../evidence/tablebases-007/README.md).

Run 001 failed preflight before any timing; a diagnostic-only unit-test target
was mistakenly included in the instrumentation validator. Run 002 repaired only
that check, with original binaries, data, repeats and thresholds. Both records
are preserved; no unfavourable sample was dropped or campaign extended.
The separate recomputation uses a different implementation by the same author;
it is not external human peer review. The reproducer is syntax/CLI checked; a
second full campaign was not run merely to repeat passing evidence.

The supported claim is lower reader metadata/startup cost with unchanged tested
answers and no regression over the declared five-percent local gate. These
changes have not been rerun against the five competitor implementations.
[Comparison 006](endgame-reader-comparison-006.md) remains evidence for its frozen
pre-change source: 13/15 wins, with WDL versus Fathom/Pyrrhic C inconclusive.
No roster-wide fastest-reader, larger-table correctness, Elo or whole-engine
strength claim follows. No Orient 017 engine checkpoint is certified here.

At adoption, the retained `build/release/` engine, reader comparison, ordered probe and search benchmark were byte-identical to the accepted native executables. That build passed 23/23 CTest groups and the full-history UCI checks. Its preservation verification checked 5,247 original packaged files and 3,028 investigation 006 files, with only ten declared source/handoff differences. The original bundle manifest and checkpoints remain intact. Subsequent [pre-upload fixes](preupload-review-2026-10-30.md) change current source and binaries; this report remains evidence for the frozen 007 campaign.

The [public evidence index](../../evidence/README.md) identifies the committed
records and the separately published raw archive. Its offline verifier recomputes
the original gates from saved raw outputs without downloading tables or running
any historical executable.
