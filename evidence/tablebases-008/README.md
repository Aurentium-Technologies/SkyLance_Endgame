# Investigation 008: current-source confirmation

**Outcome: correctness matched, but the fixed performance acceptance gates failed.**
The saved controller and separate raw recomputation both record `adopt: false`.
A `status: passed` field in a controller/audit file means the campaign completed
or its recorded calculations verified; it does not turn failed adoption gates
into a performance pass.

This campaign compares the frozen pre-007 baseline with the actual post-review
candidate, using the original 006 continuity and 007 holdout corpora and the
unchanged five AB/BA pairs. These are reused confirmation corpora, not a fresh
unseen holdout or a new competitor-confidence experiment. No trials were added,
removed or repeated to seek a favourable result.

## Results

- Exact correctness: 44 outputs, 319,972 stored rows, 4,703,656 move records,
  zero differences.
- Complete campaign: 60 reader samples, 20 search samples, 10 hot samples and
  200 fresh startup records, independently recomputed from saved raw files.
- Requested reader allocation savings: 1,966,592 bytes after initialization and
  full sweep on both corpora.
- Constructor elapsed ratio: 0.5402; configured-readiness ratio: 0.8525, missing
  its required maximum of 0.80.
- Primary WDL elapsed ratios: 1.1569 continuity and 1.5022 holdout. Several reader
  and search ratios exceed the fixed 1.05 limit. The full metric list is in
  [statistics.csv](statistics.csv); no tolerance or threshold was relaxed.

The result does not establish which change or host effect caused the observed
regressions. It does not support applying the historical 007 speed claims to
current source. Existing production defaults were not automatically changed and
no new performance candidate was adopted from this failed confirmation.

## Source and raw evidence

- [Protocol](protocol/PROTOCOL.md) and [source/input/controller freeze](protocol/freeze.json).
- [Candidate snapshot](candidate-source.json), [baseline snapshot](baseline-source.json)
  and [run bindings](run-source-binding.json).
- [Exact correctness](verification/correctness-001/result.json).
- [Full recorded result](performance/acceptance-002/result.json) and
  [separate recomputation](independent-recomputation.json).
- [Current production-source match](runtime-source-match.json) and
  [byte-identical final native runtime binaries](final-runtime-binary-equivalence.json).
- [Public file inventory and archive checksum](MANIFEST.json).

The base Git commit is 4d0e327; per-file hashes bind the actual frozen candidate,
including the intended uncommitted build/test updates. Subsequent option-cache
bookkeeping and test-registration changes do not alter the final native runtime:
engine (both executable names), reader comparison, ordered probe and search
benchmark are byte-identical to the measured candidate binaries. Public evidence
and documentation helpers added afterward are outside the timed implementation.

A preparation attempt was preserved as `aborted_before_correctness_and_timing`
when a controller guard changed after its initial hash was captured. It collected
zero correctness outputs and zero timed samples. Run-002 is the single completed
fixed campaign; the aborted record is included in the separate archive.

The [008 raw archive](https://github.com/Aurentium-Technologies/SkyLance_Endgame/releases/download/v0.1.0/skylance-evidence-008.tar.gz)
and [SHA-256 sidecar](https://github.com/Aurentium-Technologies/SkyLance_Endgame/releases/download/v0.1.0/skylance-evidence-008.tar.gz.sha256)
contain the raw outputs, frozen sources and named binary/controller provenance,
including unfavourable results. Actual table files and mutable build trees are
excluded. After checking the checksum and extracting:

```sh
python3 skylance-evidence-008/orient-endgame-component/tools/verify_public_evidence.py \
  --bundle-root skylance-evidence-008
```

This audit is offline and executes no historical binary. A fresh measurement
requires the separately downloaded tables and the explicit-candidate controller;
see the archive README and `tools/reproduce_acceptance.py --help`. Never overwrite
an existing run or extend trials to obtain a pass.
