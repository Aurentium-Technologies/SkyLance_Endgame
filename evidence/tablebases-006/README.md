# Investigation 006: public comparison records

This index publishes the frozen protocol, 540 recorded primary measurements,
statistics and descriptive per-material summaries for the historical six-reader
comparison. It describes the pre-007 source and host/workload; it does not rank
current HEAD, pure decoders, whole engines or Elo.

- [Protocol](PROTOCOL.md) and [source/input/build freeze](protocol/freeze.json).
- [Recorded campaign and all primary sample measurements](performance/run001/result.json).
- [Paired bootstrap statistics and all fifteen verdicts](performance/run001/statistics.json).
- [Descriptive per-material CSV](performance/run001/per-material.csv).
- [Latency-distribution summary](performance/run001/latency-distributions.json).
- [Original separate final audit](independent-audit-final.json).
- [Public record hashes](MANIFEST.json).
- [Report and interpretation](../../orient-endgame-component/docs/endgame-reader-comparison-006.md).

The result supports thirteen of fifteen declared operation/comparator wins; WDL
against Fathom and Pyrrhic C is inconclusive at the required five-percent margin.
No roster-wide superiority claim follows. The bootstrap unit is a complete
paired block, with the fixed seed, sample count and multiplicity adjustment in
the protocol. Per-material summaries are descriptive, not significance claims.

## Complete raw numeric audit

The separate [006 raw numeric archive](https://github.com/Aurentium-Technologies/SkyLance_Endgame/releases/download/v0.1.0/skylance-evidence-006.tar.gz)
and [SHA-256 sidecar](https://github.com/Aurentium-Technologies/SkyLance_Endgame/releases/download/v0.1.0/skylance-evidence-006.tar.gz.sha256)
publish the 540 raw latency arrays, fixed-block samples, warmups, fixtures,
correctness outputs and original pinned mathematical auditor. The archive is
about 176 MB compressed; table data, external engine source/binaries, build trees
and mutable caches are excluded.

A fresh-extraction audit verified 200,454 correctness rows with zero semantic
mismatches, all 540 primary samples and raw percentiles, 1,980 per-material
summary groups, histograms and the fixed 100,000 whole-block bootstrap draws.
It reproduced thirteen supported wins out of fifteen comparisons under the
original thresholds, seed and multiplicity adjustment.

After downloading, checking the checksum and extracting:

```sh
python3 -m venv .audit-venv
.audit-venv/bin/python -m pip install numpy
.audit-venv/bin/python skylance-evidence-006/orient-endgame-component/tools/verify_comparison_evidence.py \
  --bundle-root skylance-evidence-006
```

The local published audit was exercised with NumPy 2.5.4; its output records the
actual version. The archive executes no reader. It validates the numeric inputs,
calculations and exact-output records, not the existence/content of the 413
excluded historical binary/source bindings. Their original pins and hashes are
retained in `protocol/freeze.json` and the archive's `UNPUBLISHED-BINDINGS.json`.
It is not a complete six-reader rebuild environment or a new benchmark.

Original absolute paths are preserved as identifiers and relocated in memory;
no hash-bound records are rewritten. The [manifest](MANIFEST.json) records both
small-file hashes and the separate archive checksum.

To verify only the small committed records:

```sh
python3 orient-endgame-component/tools/verify_public_evidence.py \
  --public-dir evidence/tablebases-006
```
