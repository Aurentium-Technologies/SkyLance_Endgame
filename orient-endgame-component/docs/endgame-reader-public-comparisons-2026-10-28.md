# Public endgame reader performance comparisons

Checked 28 October 2026, New Zealand date. This is a literature/repository survey;
no new reader benchmark, source import or engine change was performed.

Public work documents faster outcome queries and improved tablebase-server
latency. None of the sources reviewed establishes a direct ranking against
Orient 016 with identical hardware, files and API work. Our retained 34.60%
probe-time reduction remains a comparison against frozen Orient 015.

## Quantitative research: alternative representations

Gomboc, Shelton, Miner and Ciardo's ECAI 2024 paper reports the following
five-piece mean outcome-query times in Table 1: Syzygy 17,160.8 ns, decision DAGs
1,312.1 ns, MTBDDs 1,513.4 ns. Dividing those means gives approximately 13.1x
and 11.3x throughput relative to that Syzygy baseline. Their alternatives use
more space and different representations. This is WCDBL outcome querying,
without DTZ or complete root move ranking; it cannot be directly compared with
our full-probe measurements. [Author-hosted paper](https://rlair.cs.ucr.edu/papers/docs/ecai24.pdf).

## Reproducible GitHub server measurements

Lichess's benchmark repository supplies a million recorded requests, replay code,
raw response-time files and plotting tools. Its accompanying author report
documents improved tail latency from I/O choices, table metadata placement and
parallel reads. It explicitly distinguishes server workloads from engines with
fast local storage. These are seven-piece HTTP-service measurements, rather
than a direct Fathom decoder comparison. [Repository](https://github.com/niklasf/lila-tablebase-bench),
[author's optimization report](https://lichess.org/@/revoof/blog/optimizing-the-tablebase-server/MetV0ZQd).

## Other readers to compare

The Rust `shakmaty-syzygy` reader has benchmark sources and an alternative probing
implementation. Its former standalone repository was merged into the current
shakmaty monorepo. I did not locate published same-workload timings showing it
beats Orient 016. [Current source](https://github.com/niklasf/shakmaty/tree/main/shakmaty-syzygy).

Pyrrhic is another Fathom-derived reader. Its README describes API/namespace
cleanup and using an engine's own utilities. I found no numeric head-to-head
speed result in that README. Its existence alone is not evidence of faster
probes. [Pyrrhic](https://github.com/AndyGrant/Pyrrhic).

## Implication for Orient

A comparison should measure raw WDL, DTZ and complete legal-alternative root
probes separately, on the same machine and files, with fresh held-out fixtures.
Pin each reader revision and preserve exact result agreement. Begin with 015,
016 and shakmaty-syzygy as external measurement comparators. Treat alternative
representations from the ECAI paper as a separate storage/research experiment.
Do not infer a fastest-reader claim or novelty of prefix lookup from our local
baseline improvement. Existing frozen checkpoints and evidence remain intact.

Survey provenance and the prior mutable goal snapshot are retained in
`artifacts/research/endgame-reader-public-comparisons-2026-10-28/`.

## Subsequent controlled comparison

The later [comparison 004](endgame-reader-comparison-004.md) pins shakmaty-syzygy
0.28.1 against Orient 016 using the same local files, shared-valid fixtures and
five rotated pairs. It reports exact common-domain values and faster Orient
query stacks on this host, with source/API, validation and memory caveats. This
subsequent experiment is separate from the literature survey above; it changes
no production reader or table format.
