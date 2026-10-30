# Five-piece comparison 006

This historical report names supporting files from the wider local research archive. Available public records and separate downloads are listed in the [evidence index](../../evidence/README.md); local-only paths below are not GitHub download links.


Completed 30 October 2026, 00:22 NZDT. Local comparison of the retained Orient 016 query stack with five pinned external implementations.

The roster-wide superiority claim is **not supported** under the frozen decision rules. Each result below is retained regardless of its direction.

The workload has 11,000 exact-five-piece static positions, 100 per each of 110 material classes, with 50 roots per side/class. It excludes prior benchmark position keys. All 290 verified three-through-five-piece tables remain available for captured children. Full legal-game reachability is not proved.

All six readers agree on supported WDL, signed nominal DTZ and complete-root values across 200,454 output rows and 2,956,938 move records. The primary 11,000 rows have no parser exclusions after freezing. Candidate parser rejections are preserved separately.

Thirty balanced blocks supply 540 timed samples, plus 18 warmups. One process/thread at a time, native Release, no LTO/PGO/result cache, warm local mmap and fixed logical CPU 0. The block is the bootstrap unit; 100,000 resamples use seed2026102906. Upper gates use one-sided Bonferroni alpha0.05/30, giving approximate 95% family-wise confidence conditional on this host/workload. Lower bounds are separately reported, not a simultaneous two-sided 95% guarantee.

A supported win requires Orient/comparator elapsed upper bound below0.95 and p95 upper below1.05. Ratios below1 favor Orient. The table reports the block-paired geometric mean and bounds.

| Comparator | Operation | Orient/other wall | Wall lower | Wall upper | p95 upper | Verdict |
|---|---|---:|---:|---:|---:|---|
| fathom | wdl | 0.8936 | 0.8277 | 0.9659 | 0.9232 | inconclusive |
| fathom | dtz | 0.7059 | 0.6530 | 0.7675 | 0.7071 | supported_win |
| fathom | all_moves | 0.6798 | 0.5943 | 0.7466 | 0.6781 | supported_win |
| pyrrhic_c | wdl | 0.9115 | 0.8400 | 1.0000 | 0.9615 | inconclusive |
| pyrrhic_c | dtz | 0.7166 | 0.6622 | 0.7795 | 0.7164 | supported_win |
| pyrrhic_c | all_moves | 0.6576 | 0.5966 | 0.7299 | 0.6611 | supported_win |
| shakmaty | wdl | 0.6369 | 0.5863 | 0.6979 | 0.7035 | supported_win |
| shakmaty | dtz | 0.5783 | 0.5357 | 0.6338 | 0.5845 | supported_win |
| shakmaty | all_moves | 0.5576 | 0.5063 | 0.6223 | 0.5763 | supported_win |
| pyrrhic_rs | wdl | 0.7015 | 0.6477 | 0.7603 | 0.7152 | supported_win |
| pyrrhic_rs | dtz | 0.6317 | 0.5810 | 0.6816 | 0.6700 | supported_win |
| pyrrhic_rs | all_moves | 0.5992 | 0.5263 | 0.6756 | 0.6530 | supported_win |
| stockfish | wdl | 0.5982 | 0.5578 | 0.6413 | 0.6497 | supported_win |
| stockfish | dtz | 0.5804 | 0.5452 | 0.6188 | 0.5718 | supported_win |
| stockfish | all_moves | 0.5353 | 0.4682 | 0.6059 | 0.5582 | supported_win |

The next table gives geometric-mean wall microseconds per query. Each operation has its own workload and must not be combined into one engine speedup.

| Reader | WDL µs | DTZ µs | Complete root µs | Root table setup ms | Root process peak MiB |
|---|---:|---:|---:|---:|---:|
| orient | 1.123 | 6.068 | 118.587 | 3.988 | 862.2 |
| fathom | 1.257 | 8.596 | 174.431 | 4.198 | 861.9 |
| pyrrhic_c | 1.232 | 8.467 | 180.333 | 3.226 | 860.0 |
| shakmaty | 1.764 | 10.493 | 212.669 | 1.144 | 821.6 |
| pyrrhic_rs | 1.601 | 9.606 | 197.899 | 3.622 | 824.1 |
| stockfish | 1.878 | 10.455 | 221.547 | 8.280 | 839.6 |

Table-setup and process-peak columns are geometric means across 30 fresh processes; raw peak ranges are retained in timing-summary.csv. Startup measures table setup after native board/attack preparation, not process launch or complete first initialization. Peak RSS includes fixtures and mapped table pages; it is not reader-only allocation or total-machine page-cache use.

These are query-stack measurements. Fathom/Pyrrhic use audited internal DTZ bridges; Stockfish complete roots reconstruct every legal move's raw value through native probes, while its native rank-only task is reported separately. Pyrrhic C uses attributed inlined Fathom attack hooks; Pyrrhic Rust uses native Shakmaty magics. Vendor probing implementations remain pinned. GPL comparison clients remain isolated from Orient.

Per-material query-latency summaries are descriptive and exclude result hashing; they do not establish significant wins for every material class. Aggregate wall measurements include consistent result consumption. No pure-decoder, universal-fastest-reader, whole-engine or Elo claim follows.

The known full-history draw loss remains open. FEN-query correctness does not certify arbitrary repetition histories. No production algorithm, history policy, profile, training configuration or checkpoint was changed.

Evidence: [protocol](../../evidence/tablebases-006/PROTOCOL.md), [freeze](../../evidence/tablebases-006/protocol/freeze.json), correctness (local archive: `../artifacts/investigations/tablebases-006/verification/result.json`), [raw campaign](../../evidence/tablebases-006/performance/run001/result.json), [statistics](../../evidence/tablebases-006/performance/run001/statistics.json), [per-material results](../../evidence/tablebases-006/performance/run001/per-material.csv), [latency histograms and raw sidecars](../../evidence/tablebases-006/performance/run001/latency-distributions.json).


Additional descriptive tasks were measured after the primary campaign, five fresh-process samples per row. Native Stockfish ranking returns ranks/scores rather than every move's raw WDL/DTZ. No matched Orient speed ratio is inferred from this separate work.

| Additional configuration/task | Operation | Wall µs/query | p95 µs | Process peak MiB |
|---|---|---:|---:|---:|
| shakmaty_pread | all_moves | 523.697 | 2196.412 | 16.7 |
| shakmaty_pread | dtz | 18.412 | 75.001 | 16.7 |
| shakmaty_pread | wdl | 3.108 | 5.830 | 16.7 |
| stockfish_native_ranked | native_ranked_root | 220.895 | 994.391 | 824.9 |
