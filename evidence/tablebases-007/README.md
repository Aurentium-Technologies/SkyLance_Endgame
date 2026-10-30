# Investigation 007: public evidence

These are byte-preserved records from the accepted historical 007 experiment.
They describe the frozen pre-upload candidate, not current HEAD and not an Elo
or universal fastest-reader claim. The [report](../../orient-endgame-component/docs/endgame-improvements-007.md)
explains the observed local measurements and their limits.

## Small records included in Git

- [Frozen protocol](protocol/PROTOCOL.md) and [source/input freeze](protocol/freeze.json).
- [Preflight-only repair record](protocol/REPAIR-002.md); the failed first attempt is retained in the release archive.
- [Complete campaign result and paired ratios](performance/acceptance-002/result.json).
- [Exact correctness summary](verification/correctness-001/result.json).
- [Separate raw-artifact recomputation](independent-recomputation.json), by the same author, not external peer review.
- [Retained-source manifest](retained-source.json) and [baseline-source hashes](baseline-source.json).
- [History-guidance proof](history-guidance-proof.md) and [review limits](code-review.md).
- [Public file hashes and release-asset checksum](MANIFEST.json).

Original absolute paths inside records are preserved because they are hash-bound
historical evidence. They are identifiers, not assumptions about your filesystem.
Do not replace their strings to relocate a campaign.

## Raw evidence and offline verification

The separately downloadable [007 evidence archive](https://github.com/Aurentium-Technologies/SkyLance_Endgame/releases/download/v0.1.0/skylance-evidence-007.tar.gz)
and its [SHA-256 sidecar](https://github.com/Aurentium-Technologies/SkyLance_Endgame/releases/download/v0.1.0/skylance-evidence-007.tar.gz.sha256)
contain the native/raw correctness outputs, every fixed acceptance timing and
startup sample, memory diagnostics, failed/rejected development evidence,
source snapshots, required earlier fixtures, and the original controllers.
Only individually hash-bound historical Orient/Fathom executables and compiler
records are retained as provenance; no included executable is run by verification.

The 290 Syzygy table files, mutable compiler trees/Cargo caches and external
measurement-opponent engine source/binaries are excluded. Source snapshot archives
and the few bytecode files explicitly hashed by the original freeze remain
historical provenance, not runtime dependencies.

After downloading both assets into one directory:

```sh
sha256sum --check skylance-evidence-007.tar.gz.sha256
tar -xzf skylance-evidence-007.tar.gz
python3 skylance-evidence-007/orient-endgame-component/tools/verify_public_evidence.py \
  --bundle-root skylance-evidence-007
```

This verifies every listed byte and runs the preserved separate auditor with an
in-memory path resolver. It recomputes all 44 exact-output comparisons, 60 reader
samples, 20 search samples, 10 hot samples and 200 fresh startup records, then
checks all original memory/startup/five-percent gates against the saved audit.
It needs Python 3.10+ only: no table download, compiler, network or executable run.
The table manifest and recorded binary digests establish which data/binaries
were used; offline raw verification does not re-execute those measurements.

Verify the small Git records independently with:

```sh
python3 orient-endgame-component/tools/verify_public_evidence.py \
  --public-dir evidence/tablebases-007
```

## Fresh measurement

A fresh campaign needs the pinned tables and a matching compiler/host setup.
Use the source checkout's `tools/reproduce_acceptance.py`; its help documents
candidate source and evidence-root arguments. The old bundled `reproduce.py`
rebuilds the frozen historical candidate; running it from a newer checkout does
not benchmark that checkout. Use new output directories and preserve all outcomes.
