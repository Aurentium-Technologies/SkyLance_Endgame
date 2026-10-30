# Reader memory and startup experiment 005

This historical report names supporting files from the wider local research archive. Available public records and separate downloads are listed in the [evidence index](../../evidence/README.md); local-only paths below are not GitHub download links.


Date: 29 October 2026, New Zealand date. **Decision: do not adopt.** The optional five-piece catalogue is implemented and verified, but stays OFF. It saves **1,966,592 requested allocation bytes (1.88 MiB)** and reduces measured constructor/configured-readiness times by **71.56% / 44.14%**, while several held-out probe and complete-search measurements exceed the agreed 5% slowdown limit. Orient 016 remains retained; no 017 checkpoint or new offline profile is created.

## Implementation and boundaries

`ORIENT_FATHOM_FIVE_PIECE_CATALOG` allocates 84 pawnless entries and 61 pawn entries, then stops discovery after the existing five-piece loops. The seven-element encoding structures, 4,096-slot material hash, disk format, decoder, prefix-length accelerator, lazy mappings and WDL/DTM/DTZ discovery within supported classes remain intact. Capacity guards prevent indexing beyond either catalogue; failure clears the partially registered dataset, frees its resources and returns unavailable.

The compiled Linux x86-64 sizes are 512 bytes per pawnless entry and 2,096 per pawn entry. Catalogue payload changes from 650/861 entries (2,137,456 bytes) to 84/61 (170,864 bytes). On the complete verified dataset, initialization open attempts fall from 1,801 to 435: all 290 successful WDL/DTZ opens remain, 145 missing DTM checks remain, and 1,366 absent six-/seven-piece WDL checks disappear.

`ORIENT_FATHOM_DIAGNOSTICS` adds tagged requested allocation/free counters and file-open/map counters in separate diagnostic builds. Its fixed ledgers are excluded from reader payload totals. Normal builds compile these hooks out; no UCI option or adapter result type changes. The original process-global provider lifetime is preserved. Position/history storage, training policy, compression, hard residency limits, eviction, online play and strength claims are outside this experiment.

The untouched Fathom control stays pinned at `c9c6fef0dddc05d2e242c183acf5833149ab676d`. Frozen 016 supplies the timing baseline. Baseline diagnostics use the same counter overlay with catalogue specialization OFF; the uninstrumented timing baseline uses the original 016 reader. The candidate uses the specialization ON. Both keep prefix hints ON, cache zero, compact cache/root reuse/profiling OFF, GNU C++ 13.3.0, Release/native optimization and no LTO. Source archives and actual compile commands are retained.

## Memory accounting and lifecycle

Both primary corpora produce the same reader-tagged allocation totals. All figures below are requested payload, not allocator footprint or total RSS.

| Phase | Baseline bytes | Candidate bytes | Saving |
|---|---:|---:|---:|
| after_init | 2,137,550 | 170,958 | 1,966,592 (92.00%) |
| after_full_sweep | 4,907,306 | 2,940,714 | 1,966,592 (40.07%) |

After the full sweep, decoding metadata is unchanged at **2,769,756 bytes in 968 allocations**, and persistent path payload is unchanged at 94 bytes. Both variants map **983,893,984 bytes** of the same table data during these traces. The full verified collection is 290 files and 983,957,920 bytes; not every file needs mapping for a particular trace.

The memory harness retains one native position and streams FENs. It records six phases: before initialization, after initialization, after first probe, after full sweep, after adapter destruction and after explicit teardown. Adapter destruction retains the global reader in both variants. Explicit teardown returns all tracked requested allocations and file mappings to zero, with balanced allocation/free and map/unmap counts. Static tables and allocator-retained pages can remain resident.

The harness separates tagged payload, allocator arena allocations, allocator-backed mappings, current anonymous memory, table virtual mappings/RSS/PSS and whole-process peak RSS. The diagnostic static counter covers only known mutable control/hash storage (98,416 bytes), not all read-only attack/index tables or ELF storage. ELF section inventories are saved separately.

Using `mallinfo2().uordblks` alone would be misleading: after the continuity sweep, arena allocations are 2,879,280 baseline versus 3,050,176 candidate, but allocator-backed mappings are 2,142,208 versus zero. The candidate saves payload despite a larger arena-only figure. Diagnostic bookkeeping and unrelated process allocations also appear in these allocator totals. Broad table-page RSS remains about 795–801 MiB on these traces. This is metadata savings, not compression or a hard RAM bound.

## Startup and speed acceptance

The frozen protocol uses five alternating paired trials with fresh processes, prewarmed OS cache and the exclusive project compute lease. Each variant/pair has 20 fresh reader constructions and 20 fresh UCI processes: **200 constructor samples and 200 UCI startup samples** in total. Pair summaries are medians of 20; ratios are geometric means of paired medians. UCI timings begin at table-path configuration after initial engine setup and FEN preparation, excluding process launch.

| Startup metric | Baseline ms | Candidate ms | Candidate / baseline |
|---|---:|---:|---:|
| Reader constructor | 3.566 | 1.014 | 0.284364 |
| Configure through readyok | 6.792 | 3.794 | 0.558646 |
| Configure through first root result | 7.272 | 4.242 | 0.583385 |

The primary timing sets contain 9,985 continuity and 9,975 disjoint held-out positions, each covering all 145 three- through five-piece material classes. WDL repeats 20 times, DTZ ten and complete alternatives three. The deterministic 145-class hot set repeats 96 times. Complete covered-root and 48 six-piece descendant searches run at depth four with three repetitions. All raw first-use, CPU where available, elapsed and percentile measurements remain saved. UCI/search CPU fields are unavailable and are explicitly null.

The table shows paired geometric-mean elapsed-time ratios. Values above 1.05 fail the regression gate. Each row is a separate workload.

| Workload | Continuity ratio | Holdout ratio |
|---|---:|---:|
| Warm WDL | 0.844092 | **1.222009** |
| Warm DTZ | 0.872053 | **1.229717** |
| Complete root alternatives | 0.998090 | **1.120764** |
| First WDL sweep | 0.847376 | **1.173136** |
| First DTZ sweep | 0.884685 | **1.203126** |
| First complete-root sweep | 0.952246 | **1.185215** |
| Complete covered-root searches | **1.120782** | 0.990098 |
| Complete covered-root p95 | **1.124422** | 0.990285 |
| Six-piece descendant searches | 1.016732 | **1.053441** |

Hot complete-probe elapsed/p95 ratios are 0.974194 / 0.971735; first-hot-sweep ratio is 0.924232. Startup targets and the minimum 1 MiB saving pass. However, held-out WDL/DTZ elapsed times increase **22.20% / 22.97%**; continuity complete-root search time increases **12.08%**, and held-out descendant-search time increases **5.34%**. Other first-sweep and p95 gates also fail.

There is substantial pair variability: held-out DTZ elapsed ratios range approximately 0.797–2.142, and continuity root-search ratios 0.852–1.581. The first baseline startup pair is also slower than later pairs. All samples are retained. These observations do not isolate whether layout, clock behavior or other host effects caused the differences. The prescribed decision remains **reject adoption**; no failed pair was discarded or acceptance timing selectively repeated.

## Correctness and verification

- All **12,010 original upstream cases** pass at cache 0/1/4/16 MiB against both baseline and candidate, with exact recommendations and native alternative order.
- All **21,963 shared-valid cases** pass raw WDL, signed nominal DTZ and root-value comparison against 016, plus native recommendation/ordered-alternative comparison. The 52 parser exclusions from experiment 004 remain recorded and unchanged.
- The complete correctness run saves **36 outputs, 231,972 rows and zero differences**. A non-lexicographic order witness prevents accidentally sorted output from masquerading as native order.
- Catalogue tests cover complete, partial, empty and missing collections, ignored larger-material filenames, retained DTM discovery, repeated paths, forced overflow of each capacity, full rollback and recovery. Existing mapping-failure, restriction, promotion/underpromotion, en-passant, near-limit clock, terminal, repetition, finite/infinite analysis and interruption regressions pass.
- All **136 CTest groups pass**, zero failures or skips: release 35, native 35, debug 33, sanitizer 33. Debug/sanitizer preserve the existing two extended-perft exclusions. Address/undefined-behaviour checks are enabled; leak detection uses the existing sandbox setting `detect_leaks=0`. Explicit reader ownership/mapping balance is checked separately.
- Loaded-path/probe-limit-zero UCI checks preserve moves, scores and node counts across 18 searches; CLI depth-six results also match frozen 016. The default-off reader object is **byte-identical to the reader rebuilt from frozen 016**. Normal binaries contain no diagnostic snapshot/counter symbols.
- An independent audit recomputes all 43 timing ratios, the 20-sample startup medians, payload savings, raw hashes and the failed adoption decision. The new controller has 25 guard tests, including a pre-timing CMake-comment parser repair; the strict verifier has 13 tests. No acceptance sample existed before that guard repair.

The prototype preserves all measured chess results. This does not fix the separate history-sensitive draw-loss issue recorded in playing diagnostic 001, or establish stronger play. No game or rating campaign was started.

## Delivery and reproduction

Both new build options remain **OFF**. Orient 016 and all earlier candidates/profiles remain intact. No 017 freeze or new profile is appropriate because the performance gate failed. The implementation, diagnostic tooling, negative results and reproducible patch remain available for later research.

Configure a separate native Release build with catalogue ON and diagnostics OFF for the prototype; use a separate diagnostics-ON build for memory attribution. The timing baseline is reconstructed from 016 plus the common measurement clients. Keep encoding dimensions seven and all other experimental settings OFF. Run the saved correctness configuration, then the saved performance configuration into fresh directories using the corresponding verifier/controller. Neither starts games or training.

- Frozen protocol (local archive: `../artifacts/investigations/tablebases-005/PROTOCOL.md`), performance configuration (local archive: `../artifacts/investigations/tablebases-005/performance-config.json`) and all timing/diagnostic results (local archive: `../artifacts/investigations/tablebases-005/performance/result.json`).
- Exact correctness result (local archive: `../artifacts/investigations/tablebases-005/correctness/result.json`), independent audit (local archive: `../artifacts/investigations/tablebases-005/independent-audit.md`) and disabled/default-off checks (local archive: `../artifacts/investigations/tablebases-005/postchecks.json`).
- Four-build verification (local archive: `../artifacts/investigations/tablebases-005/verification.json`), fork patch check (local archive: `../artifacts/investigations/tablebases-005/fork-patch-check.json`) and pre-timing guard repair (local archive: `../artifacts/investigations/tablebases-005/preflight-guard-fix.md`).
- [Local fork record](../third_party/fathom/FORK.json) and [optional source delta](../third_party/fathom/five-piece-catalogue.patch); upstream MIT attribution remains retained.
