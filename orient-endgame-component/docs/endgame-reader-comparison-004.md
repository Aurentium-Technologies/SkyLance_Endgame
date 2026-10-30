# Orient 016 versus shakmaty-syzygy: comparison 004

Completed 28 October 2026, New Zealand date. On this machine and these warm-cache native query workloads, **Orient 016 is faster than pinned shakmaty-syzygy** with exact common-domain results. The primary mmap comparison gives Orient **1.55–1.67× WDL throughput, 1.67–2.02× DTZ throughput and 1.58–2.00× complete-root throughput** across the two corpora. Each range describes the two five-pair geometric means, not a confidence interval. Shakmaty initializes faster.

These are query-stack timings, including implementation-specific board, move generation, validation and wrapper work. They do not isolate decoder speed, measure complete Orient searches, establish a portable fastest reader, or demonstrate Elo gain. No reader replacement or new engine candidate is adopted.

## Pinned inputs and work

- Orient is the source of frozen `orient-016-reader-prefix`, with its retained prefix-length accelerator ON, cache zero, compact-cache/root-legal-reuse/profiling experiments OFF. The measurement executable is rebuilt from that archive with a standalone harness overlay; it is not the frozen UCI executable. Fathom upstream pin remains `c9c6fef0dddc05d2e242c183acf5833149ab676d`.
- Shakmaty monorepo commit is [`eb36a609da25b7f76e1ff94bbf1af7e0be53d990`](https://github.com/niklasf/shakmaty/tree/eb36a609da25b7f76e1ff94bbf1af7e0be53d990/shakmaty-syzygy), dated 26 October 2026: `shakmaty-syzygy` 0.28.1 and `shakmaty` 0.30.2. The GPL comparison client and dependency are separate from Orient; neither is linked into the engine or used for training/play. Source archive, licence, Cargo.lock and binary hashes are retained.
- Both use the verified local collection: **290 WDL/DTZ files, 983,957,920 bytes**, manifest SHA-256 `7d4eae2c333da3b8b9e485e0496efc56a07b4452e2bb53e83cfa6bceb9c7a73d`. No format conversion or network service is involved in probing.
- Linux x86-64, Intel Core i7-10810U; GNU C++ 13.3.0 versus workspace-local Rust 1.97.0. Both use release/native optimizations, no LTO and one query thread. Rust uses one codegen unit. The Rust runtime was downloaded locally with official published SHA-256 checks; no host toolchain/profile or restrictive perf setting was changed.

Raw WDL uses Orient’s actual adapter versus `probe_wdl_after_zeroing`, with the same zero-halfmove eligibility envelope. Single DTZ uses a measurement-only shim into Fathom’s existing internal primitive versus Rust’s public `probe_dtz`; it is not a new production API. One Fathom implementation is linked. Both classify mate/stalemate before primitive DTZ timing.

Complete roots use Orient’s actual root adapter, including native recommendation and validation work, versus a Rust envelope that probes the root and **every legal child** with matching Fathom DTZ/clock conventions. Native Rust `best_move` does less work and returns child DTZ, so it is diagnostic only. Both time legal generation, adjudication, UCI normalization and sorting. C++ adds another normalized vector; Rust uses fixed UCI fields. See the [independent harness audit](../artifacts/investigations/tablebases-004/cpp-harness-audit.md).

## Correctness and the input-domain discovery

The initial 22,015 synthetic fixture rows exposed **52 parser rejections**: 20 continuity, 30 holdout and two special rows. Shakmaty rejects them as `illegal position: impossible check`; Orient’s static FEN checks accept them. There were no numerical disagreements among mutually accepted rows. The original `needs_review` report and every rejected FEN remain preserved. Rust validation was not relaxed.

Before timing, the common domain was fixed using only parser acceptance, with no value/speed filtering. Both primary sets still span **all 145 three- through five-piece material classes**. The holdout seed is `2026102804`; its FEN set is disjoint from continuity. These are synthetic static positions accepted by both validators; full game reachability is not proved.

| Corpus | Parent rows | Shared rows | Excluded | Raw WDL success / unsupported | DTZ and root success / unsupported |
|---|---:|---:|---:|---:|---:|
| Continuity | 10,005 | 9,985 | 20 | 9,985 / 0 | 9,985 / 0 |
| Fresh holdout | 10,005 | 9,975 | 30 | 9,975 / 0 | 9,975 / 0 |
| Special | 2,005 | 2,003 | 2 | 4 / 1,999 | 2,002 / 1 |

All **21,963 shared rows** have identical operation statuses and, where supported, exact raw WDL, signed nominal DTZ, clock-derived nominal WDL and complete legal-alternative values. There is no ±1 DTZ tolerance. The typed audit validates **65,889 output rows and 916,500 move records** across three variants, with zero errors. Special coverage includes en passant, promotions/underpromotions, both sides, mate, stalemate, castling rejection and halfmove counters 98/99. There are 305,500 alternative records per reader, including 2,463 underpromotions.

Native recommended moves differ on 2,722 continuity, 2,777 holdout and 549 special rows. Each recommendation is legal and has the best nominal WDL; tie/conversion policies differ. Shakmaty reports rounded-DTZ metadata, which Fathom’s interface does not expose. That flag is diagnostic and excluded from equality/hashes, while the returned DTZ integers are compared exactly. Clock-derived values are the documented nominal contract, not a proof from arbitrary prior repetitions. FENs contain no earlier history; repetition-aware search is outside this comparison.

## Paired timings

The protocol was frozen after correctness and before timing. **Five rotated paired trials, 90 samples and 18 warmups** use fresh processes, prewarmed OS cache and an exclusive shared Orient compute lease. WDL repeats each primary corpus 20 times, DTZ ten times and complete roots three times. Parsing/native fixture storage precede timings. Reader construction, first pass and repeated queries are separate. Repeated wall time includes query work, latency recording and consuming normalized result hashes; per-query latency excludes hashing. JSON output and percentile sorting occur afterwards.

The following are geometric means of repeated wall microseconds per top-level query. “Orient throughput” is the paired shakmaty/Orient elapsed-time ratio; larger than one favours Orient. Each operation is a separate workload.

| Corpus | Operation | Orient mmap µs | Shakmaty mmap µs | Orient throughput | Five pair ratio range |
|---|---|---:|---:|---:|---:|
| Continuity | WDL | 1.106 | 1.719 | 1.554× | 1.273–1.913× |
| Continuity | DTZ | 6.385 | 12.905 | 2.021× | 1.363–2.600× |
| Continuity | Complete root alternatives | 86.439 | 172.754 | 1.999× | 1.488–2.998× |
| Holdout | WDL | 1.017 | 1.699 | 1.671× | 1.112–2.666× |
| Holdout | DTZ | 6.606 | 11.026 | 1.669× | 1.300–2.160× |
| Holdout | Complete root alternatives | 96.927 | 152.711 | 1.576× | 1.056–1.920× |

Every individual primary mmap pair favours Orient. Ratios vary materially on this laptop; the table retains the full pair ranges rather than treating the means as exact portable constants. CPU ratios closely track elapsed ratios. This lease prevents overlapping Orient heavy experiments; it does not eliminate normal desktop activity or lock CPU frequency.

| Corpus | Operation | Orient p95 µs | Shakmaty mmap p95 µs | Shakmaty pread / Orient wall ratio |
|---|---|---:|---:|---:|
| Continuity | WDL | 2.093 | 3.194 | 2.899× |
| Continuity | DTZ | 22.942 | 49.568 | 3.171× |
| Continuity | Complete root alternatives | 386.363 | 830.012 | 3.142× |
| Holdout | WDL | 1.930 | 3.130 | 3.172× |
| Holdout | DTZ | 23.450 | 42.429 | 2.928× |
| Holdout | Complete root alternatives | 434.817 | 742.641 | 2.951× |

Rust’s default `pread` backend is slower here than its mmap backend, with roughly 2.90–3.17× Orient’s elapsed time. That is an I/O/backend observation for local warm files, not evidence about a seven-piece remote tablebase service. No cold-disk or concurrent-server workload was measured.

## Initialization, first use and memory

Construction is timed after FEN parsing. It excludes process launch and lazy first-probe metadata work; the first sweep captures that separate first-use cost. Geometric means below use the complete-root samples. All raw first-pass CPU/elapsed, pre-probe high-water RSS and per-sample results remain in the result JSON.

| Corpus | Reader/backend | Construction ms | First complete-root sweep ms | Whole-process peak MiB |
|---|---|---:|---:|---:|
| Continuity | orient016 | 3.703 | 922.5 | 816.0 |
| Continuity | shakmaty_mmap | 1.125 | 1873.2 | 779.6 |
| Continuity | shakmaty_pread | 1.110 | 3761.2 | 21.5 |
| Holdout | orient016 | 3.952 | 966.2 | 820.3 |
| Holdout | shakmaty_mmap | 0.929 | 1588.1 | 784.2 |
| Holdout | shakmaty_pread | 1.003 | 3836.8 | 21.5 |

Shakmaty’s construction is faster. Its mmap peak RSS is lower, but these totals include different native fixture representations: Orient reserves 1,024 history keys per parsed position. Pread’s approximately 21.5 MiB process RSS excludes table pages retained in the kernel page cache. These measurements therefore do **not** establish reader-only allocated memory, whole-machine memory savings or a new RAM bound. Allocation counts were not measured.

## Verification, preservation and next implication

All normalized repeated and first-pass hashes agree. The standalone Rust client passes four unit tests; the Python controller/semantic guards pass 25 tests. Independent audits check timing boundaries, exact values, recommendation legality and typed output. The frozen canonical verifier is not a comprehensive malformed-JSON schema validator; the separate typed audit verifies all actual recorded outputs. No production engine source changed, so this task did not rerun the engine’s release/debug/sanitizer suite or claim a new engine release. The earlier 016 verification remains preserved.

Post-run SHA-256 checks preserve candidates 015/016, their source archives and copied manifests, and all 27 production source/build-definition/licence files checked against 016. The controller revalidates every table file and all pinned performance inputs after timing. Profiles were not edited. Comparison binaries, source pins, licences, fixtures, exclusions, protocol, raw trials, audit scripts and results are retained in investigation 004. No online game, rating campaign or training-policy change occurred.

The evidence supports retaining Orient 016’s current reader for the next experiment. There is no measured speed reason here to replace it with shakmaty. Further optimization should begin with profiling the remaining DTZ/complete-root costs in Orient; this comparison alone does not identify which decoder, indexing or move-adjudication operation dominates. A controlled complete-search benchmark would be required before claiming whole-engine improvement.

## Reproduction and evidence

- [Frozen measurement protocol](../artifacts/investigations/tablebases-004/measurement-protocol.md) and [reproduction steps](../artifacts/investigations/tablebases-004/reproduction.md).
- [Performance configuration](../artifacts/investigations/tablebases-004/performance-config.json) and [all trials/results](../artifacts/investigations/tablebases-004/performance/result.json). See the [independent saved-result audit](../artifacts/investigations/tablebases-004/performance-audit.md).
- [Passed strict comparison](../artifacts/investigations/tablebases-004/correctness-shared/result.json), [typed audit](../artifacts/investigations/tablebases-004/typed-values-audit.json), and [independent semantics notes](../artifacts/investigations/tablebases-004/semantics-notes.md).
- [Original parser differences](../artifacts/investigations/tablebases-004/correctness/differences.json) and [selection provenance](../artifacts/investigations/tablebases-004/fixture-provenance.json).
- [Reader pin](../artifacts/investigations/tablebases-004/shakmaty-pin.json), [toolchain pin](../artifacts/investigations/tablebases-004/toolchain-pin.json), [builds](../artifacts/investigations/tablebases-004/harness-builds.json), [preservation checks](../artifacts/investigations/tablebases-004/preservation.json), and [test log](../artifacts/investigations/tablebases-004/python-tests.log).
