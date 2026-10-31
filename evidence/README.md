# Public research evidence

SkyLance's source repository keeps small research records in Git and publishes
larger raw evidence separately. Actual Syzygy table data is excluded from both;
the [pinned catalogue](../orient-endgame-component/tools/syzygy345.json) records
the data URLs, sizes and SHA-256 values needed for a separate download.

| Investigation | Public records | Interpretation |
| --- | --- | --- |
| [006 comparison](tablebases-006/README.md) | Protocol/freeze, all 540 recorded primary measurements, statistics, per-material CSV and original audit summary. | Historical pre-007 six-reader comparison: thirteen of fifteen declared wins; no roster-wide superiority. A separate 176 MB raw archive recomputes correctness, latency percentiles and the 100,000-draw bootstrap; external-reader rebuild payloads remain excluded. |
| [007 improvements](tablebases-007/README.md) | Protocol/freeze, results, correctness and source/proof records in Git; separately downloadable raw evidence and portable offline verifier. | Frozen historical candidate: exact tested answers, smaller reader metadata and local startup/query measurements within the declared gate. This is not a measurement of later HEAD or an Elo claim. |
| [008 current-source confirmation](tablebases-008/README.md) | New frozen-source records, full results, derived statistics and final-runtime binary equivalence; separate raw archive. | Exact answers match, but configured readiness and regression gates fail (`adopt: false`). Historical 007 speed claims are not certified for current source. |

The 008 controller completed the fixed campaign once. Its unfavourable result is
preserved rather than replaced by extra trials. See each index for the complete
scope, archive checksums and verification instructions.

## Check the committed records

From the repository root:

```sh
python3 orient-endgame-component/tools/verify_public_evidence.py --public-dir evidence/tablebases-006
python3 orient-endgame-component/tools/verify_public_evidence.py --public-dir evidence/tablebases-007
python3 orient-endgame-component/tools/verify_public_evidence.py --public-dir evidence/tablebases-008
```

These commands verify the public record bytes against their inventories. They do
not substitute for checking the larger raw archive.

## Check the raw 007 archive

Download [skylance-evidence-007.tar.gz](https://github.com/Aurentium-Technologies/SkyLance_Endgame/releases/download/v0.1.0/skylance-evidence-007.tar.gz)
and its [SHA-256 sidecar](https://github.com/Aurentium-Technologies/SkyLance_Endgame/releases/download/v0.1.0/skylance-evidence-007.tar.gz.sha256).
The approximately 25.4 MB compressed archive contains the fixed raw 007 campaign,
frozen sources, required earlier fixtures/controllers and individually hash-bound
historical Orient/Fathom binary/compiler provenance. It excludes table data,
mutable build trees and external measurement-opponent engines.

```sh
sha256sum --check skylance-evidence-007.tar.gz.sha256
tar -xzf skylance-evidence-007.tar.gz
python3 skylance-evidence-007/orient-endgame-component/tools/verify_public_evidence.py \
  --bundle-root skylance-evidence-007
```

This performs the preserved separate raw-artifact recomputation without running
any included executable or needing table files, a compiler or network access.
It checks exact outputs, paired ratios, startup medians, memory and all original
gates. It is a separate implementation by the same author, not external peer
review. Old absolute paths are resolved in memory; hash-bound originals remain
unchanged. See each investigation index for the exact scope and remaining limits.

## Other historical reports

Supporting records for older investigations 001–005 and the playing diagnostic
remain in the original local research archive unless explicitly included as a
dependency of these bundles. Their reports show local-only paths as text rather
than broken download links. The published archives do not claim complete
reproduction of every earlier experiment.
