# Current Orient endgame system compared with GitHub systems

Checked 29 October 2026, New Zealand date. The retained system is **Orient 016 behavior**, with its Fathom prefix accelerator ON, runtime WDL cache zero, and the catalogue, diagnostics, compact-cache, root-list-reuse and profiling experiments OFF. The current reader includes disabled experiment 005 code; its entire source is not byte-identical to the frozen 016 source.

The strongest available result favors Orient over pinned **shakmaty-syzygy 0.28.1** on this machine's measured warm query workloads. It does not establish a fastest-reader ranking across GitHub projects. Orient uses attributed Fathom infrastructure; these results do not describe an independently invented tablebase format or solver.

This review verified the existing package and audited saved results. **No new timed benchmark, build, game or engine change was performed.** The timings below were collected on 28 October. The original packaged files and benchmark evidence remain unchanged.

The comparison used Linux x86-64, an Intel Core i7-10810U, GNU C++ 13.3.0 and Rust 1.97.0; one query thread; Release/native optimization without LTO; and the same 290 WDL/DTZ files totaling 983,957,920 bytes. Both timing corpora span all 145 three-through-five-piece material classes. Five pieces includes both kings and pawns. These are mixed three-through-five-piece results; no isolated five-piece-only timing is established here.

Five rotated paired trials used 9,985 continuity positions and 9,975 disjoint held-out positions. The table reports geometric means of repeated wall microseconds per top-level query. The throughput ratio is Shakmaty elapsed time divided by Orient elapsed time; larger than one favors Orient.

| Corpus | Operation | Orient µs/query | Shakmaty mmap µs/query | Orient throughput ratio | Individual-pair ratio range |
|---|---|---:|---:|---:|---:|
| Continuity | WDL outcome | 1.106 | 1.719 | 1.554× | 1.273–1.913× |
| Continuity | DTZ | 6.385 | 12.905 | 2.021× | 1.363–2.600× |
| Continuity | All legal root alternatives | 86.439 | 172.754 | 1.999× | 1.488–2.998× |
| Held-out | WDL outcome | 1.017 | 1.699 | 1.671× | 1.112–2.666× |
| Held-out | DTZ | 6.606 | 11.026 | 1.669× | 1.300–2.160× |
| Held-out | All legal root alternatives | 96.927 | 152.711 | 1.576× | 1.056–1.920× |

All 30 primary paired comparisons favor Orient. Shakmaty's pread backend takes approximately 2.90–3.17 times Orient's elapsed time on these warm local workloads. Pair ranges show considerable laptop variability; the means are not portable constants or confidence intervals. The [original comparison](../../orient-endgame-component/docs/endgame-reader-comparison-004.md), [frozen protocol](../../orient-endgame-component/artifacts/investigations/tablebases-004/measurement-protocol.md) and [raw results](../../orient-endgame-component/artifacts/investigations/tablebases-004/performance/result.json) describe the measurement boundaries.

These timings include implementation-specific board, validation, move generation and wrapper work. WDL and complete-root measurements use Orient's actual adapter; primitive DTZ uses a measurement shim. The Rust complete-root envelope evaluates every legal child. Its native best-move routine performs less work and is excluded from the primary ranking. This evidence measures query stacks, rather than isolated decoder cycles, complete engines or Elo.

Shakmaty has a startup advantage: its mmap constructor takes approximately **0.93–1.13 ms**, compared with Orient's **3.70–3.95 ms**. Recorded mmap process peaks are roughly 780–784 MiB versus Orient's 816–820 MiB, but the harnesses store fixtures differently, including Orient's reserved history capacity. Shakmaty pread's approximately 21.5 MiB process peak excludes kernel page cache. These measurements do not establish reader-only RAM use or total-machine memory savings.

The live GitHub survey found the following comparison opportunities and published claims. Each claim retains its own baseline and workload; the numbers cannot be combined into a league table.

| GitHub system | Published or available benchmark evidence | Comparison with current Orient |
|---|---|---|
| [Fathom](https://github.com/jdart1/Fathom) | C/C++ WDL, DTZ and complete-root API; no numerical speed table in the inspected README. Orient's preserved exact differential covers 12,010 cases at cache 0/1/4/16 MiB against pinned upstream. | Closest architectural control. No matched upstream-Fathom speed ratio is established by this review. |
| [shakmaty-syzygy](https://github.com/niklasf/shakmaty/tree/eb36a609da25b7f76e1ff94bbf1af7e0be53d990/shakmaty-syzygy) | Its [0.28.1 changelog](https://github.com/niklasf/shakmaty/blob/eb36a609da25b7f76e1ff94bbf1af7e0be53d990/shakmaty-syzygy/CHANGELOG.md) reports approximately 10× faster in-memory probing after removing decompression syscalls; that line does not specify hardware/corpus. The repository also has a single-position six-piece WDL microbenchmark. | The local comparison already uses 0.28.1, including this improvement. The controlled results above provide the relevant direct comparison. |
| [Pyrrhic](https://github.com/AndyGrant/Pyrrhic) | Fathom-derived C reader with engine-utility integration; no numerical speed table in its inspected README. | No measured ranking against Orient. A fair C comparison should hold API work and engine utilities constant. |
| [Pyrrhic Rust fork](https://github.com/starius/pyrrhic-rs), integrated into Ember | [Ember PR 56](https://github.com/ExxDreamerCode/Ember/pull/56) reports aggregate engine NPS ratio **1.0154**, individual positions **0.9848–1.1056**, from four roots and nine interleaved paired repeats, with identical moves, scores and nodes. | An author-reported approximately 1.54% engine-throughput gain in that development comparison. It does not time isolated probes or compare against Orient. The throughput passage does not precisely pin the timing baseline. |
| [python-chess](https://github.com/niklasf/python-chess/blob/master/docs/syzygy.rst) | Independent WDL/DTZ implementation and documented rule-50/rounding semantics; no matched Orient timing established in the inspected material. | Useful correctness reference. A language-level speed assumption would not be benchmark evidence. |
| [lila-tablebase-bench](https://github.com/niklasf/lila-tablebase-bench) | One million production requests, 12 clients, 800,000 warmup requests and 200,000 analysed requests. [Author report](https://lichess.org/@/revoof/blog/optimizing-the-tablebase-server/MetV0ZQd) evaluates a seven-piece server with HDD/NVMe storage; an average request generates 23 WDL and 70 DTZ probes. | Measures service/storage latency. Its finding that pread improves server tails can coexist with mmap being faster in a local engine workload. No numerical speed ratio against Orient is justified. |
| [syzygy1/tb](https://github.com/syzygy1/tb) | Tablebase generator and storage information. | Generation time and compressed file size measure different work from reader probes. |

The Rust fork's [historical validation report](https://github.com/starius/pyrrhic-rs/blob/3801b3e6c48311f7834c11e7652e7b3d65863161/docs/validation.md) reports 4,271,533 development requests without mismatches. It explicitly predates the standalone fork, does not exercise every request through Ember's adapter, and retains raw artifacts on a private development host. It is useful author-reported coverage, not an independently reproduced correctness guarantee. [ChessTB](https://github.com/noobpwnftw/chesstb) is another relevant alternative representation with additional metrics and castling tables, but no directly comparable speed result was located in the inspected material.

Orient's separate **34.60% probe-time reduction and 31.04% covered-root search reduction** are against frozen **Orient 015**. They must not be presented as direct raw-upstream-Fathom benchmark results. See [experiment 003](../../orient-endgame-component/docs/endgame-reader-optimization-003.md).

The latest five-piece catalogue prototype saved **1,966,592 requested allocation bytes (1.88 MiB)** and improved startup, but held-out WDL/DTZ time increased **22.20%/22.97%** under its prescribed experiment. It failed the five-percent regression gate and remains OFF. No Orient 017 is retained. See [experiment 005](../../orient-endgame-component/docs/endgame-reader-memory-005.md).

Correctness agreement covers **21,963 shared-valid positions**, with exact supported WDL, signed nominal DTZ, clock-derived nominal WDL and all legal-alternative values. Fifty-two synthetic positions were excluded before timing solely because Shakmaty rejected impossible-check FENs; no numeric mismatches were found among mutually accepted rows. Native recommendations can differ through tie/conversion policy. The sampled fixtures do not prove full game reachability or exhaust every five-piece position.

The known full-history draw loss remains open: playing diagnostic 001, record 53, ply 37. A FEN query cannot certify arbitrary repetition-history behavior. Faster reader results therefore do not justify claims of perfect endgame play. See the [playing diagnostic](../../orient-endgame-component/docs/endgame-playing-001-2026-10-28.md).

Today's fresh verification passed all **5,247 packaged files (1,279,498,907 bytes)** and independently checked the complete 290-file publisher table collection. The [fresh evidence audit](current-evidence-audit.json) recomputed all six primary timing ratios, confirmed all 30 paired wins, checked saved-output SHA-256 values, and rechecked **65,889 typed rows and 916,500 move records**, with exact common-domain agreement. Six current adapter/board/harness files match frozen comparison 004. [The audit script](audit_saved_evidence.py) can be rerun without running timed probes. Original manifests, source, configurations and saved results remain unchanged.

The evidence supports retaining 016. The most useful next correctness work is the known history-sensitive integration case. For a broader speed ranking, the missing experiment is an untouched upstream-Fathom and Pyrrhic comparison using the same API work, fixtures, files, compiler settings and paired timing protocol; a five-piece-only breakdown would also sharpen the current mixed-material result.
