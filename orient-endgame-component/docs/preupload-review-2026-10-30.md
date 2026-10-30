# SkyLance pre-upload review, 30 October 2026

The current implementation was reviewed and corrected before GitHub publication.
The portable Release build passes all 24 CTest groups with local table data, and
all 132 Python unit tests pass. A separate copy containing only Git-selected
files also builds, installs and passes its source-only checks. No GitHub upload,
remote configuration, commit or new performance campaign was performed.

## Fixed findings

| Priority | Finding | Correction and regression evidence |
| --- | --- | --- |
| P1 | Reader teardown freed catalogue entries while material hashes retained pointers. A direct WDL probe after `tb_free()` could dereference freed storage. | Reset hashes, counts and public/internal cardinalities before empty-path initialization returns. ASan reproduced the original use-after-free; adaptive and fixed catalogue tests now cover post-free probes and both empty sentinels. |
| P1 | A raw reader path list ending in a platform separator counted its terminating NUL as another directory and read beyond allocated storage. | Count only nonempty components. ASan reproduced the original buffer overflow; regressions cover leading, repeated, trailing and separator-only lists. The engine adapter already restricts its input to one directory. |
| P2 | Correctness comparisons could pass with no corpus or one reader, and readers could agree on the same wrong FEN inputs. Timing comparisons accepted empty corpora. | Require multiple reader variants and nonempty, hash-bound input rows. Validate exact FEN, integer line order and boolean parse status for every reader, verify the dataset binding, and reject ambiguous JSON. Added negative regressions for these false-pass paths. |
| P2 | Time allocation multiplied or added unbounded `int64` clock values, causing signed overflow through the direct search API. UCI's narrower numeric bounds prevented this specific input through UCI. | Use bounded arithmetic before summing increments and multiplying hard budgets. The new full-range clock regression failed before the fix and passes afterward; ordinary clock allocation is preserved. |
| P2 | New checkpoint records emitted `cmake --preset` commands although this focused component has no presets. | Emit explicit configure/build commands when presets are absent, preserving recorded build type and `ORIENT_` feature flags. Legacy preset trees keep their existing commands. Three focused regressions pass. |
| P3 | Importing referee tests during standard unittest discovery treated discovery arguments as an executable path. | Parse explicit executable arguments only in script mode; discovery uses the configured/default referee and reports missing optional dependencies honestly. The complete discovery suite now runs. |

Current changes are in `third_party/fathom/src/tbprobe.c`, `src/search.cpp`,
`tools/verify_reader_comparison.py`, `tools/measure_reader_comparison.py`,
`tools/checkpoint.py` and their focused tests. The maintained reader's
`FORK.json` hashes match the source. New `teardown-state.patch` and
`path-list.patch` reconstruct the additional changes after the existing patch
chain; reconstruction was compared byte for byte.

## Branding and source publication

The UCI name, version/help output and installed executable use **SkyLance**. UCI
identifies **Aurentium Technologies** as author. Both `skylance` and the historical
`orient` target build the same implementation; installation and UCI lifecycle
tests use `skylance`. Existing namespaces, options, network format and original
licence notices remain compatible. The supplied banner, logo and emblem retain
their original bytes and pass `assets/branding/SHA256SUMS`.

`.gitignore` excludes local solved-position files, build trees, caches, frozen
checkpoints, raw investigation artifacts, name-check research and machine
configuration. Source, tests, public documentation, branding, licences and the
pinned upstream Fathom comparison source remain publishable. The selected tree
is about 5.4 MB rather than the roughly 2 GB working research folder. The file
selection check found no symlinks, files over GitHub's 100 MiB limit, or common
private-key/GitHub/AWS credential signatures. That bounded check is not an
exhaustive security audit.

The GitHub workflow builds a portable Release, runs source-only CTest checks,
installs the engine and verifies branding checksums. It uses the official
[checkout v7.0.1 release](https://github.com/actions/checkout/releases/tag/v7.0.1)
with read-only repository permissions. It has been checked locally; no hosted
workflow has run yet. GitHub documents its file-size boundary in
[About large files](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).

## Validation performed

- Clean GNU C++ 13.3.0 portable Release configure/build, `ORIENT_NATIVE=OFF`:
  **24/24 CTest groups passed**, with no skips when the complete local tables
  were configured. This includes real-table UCI, provider/cache lifecycle,
  history/search, map failure and scalar 32/64-bit prefix checks.
- Full Python discovery with the current built referee and local table path:
  **132 tests passed**, with no skips.
- Independent fresh copy of all Git-selected implementation files, with table
  data and artifacts absent: configure/build/install succeeded; **20 CTest
  groups passed, four table-dependent groups skipped, zero failed**. Adding the
  original absolute table path then passed **24/24 groups**. The published code
  hashes matched this independently tested copy.
- Focused Debug ASan/UBSan checks passed for reader teardown/path parsing,
  adaptive catalogue, search internals, search/evaluation (1,144 checks), chess
  queries (332,193 checks), and real-table history/endgames. Leak detection was
  disabled for the execution environment; no leak-check result is claimed.
- All **290 table files / 983,957,920 bytes** matched the pinned publisher
  catalogue. This check was offline and did not change the dataset.
- Installation to a temporary prefix produced `bin/skylance`, reporting
  **SkyLance 0.1.0**. All three branding checksums and current Fathom source
  digests passed.

An initial integration build started while the reader fix was still being
edited and retained a stale standalone test object; its path-list regression
failed. A clean rebuild and the independent fresh copy both passed that case.
Acceptance above uses the clean builds. Known warnings remain in inherited
diagnostic/test code; the build does not treat warnings as errors.

## Reproduction and limits

From the repository root:

```sh
cmake -S orient-endgame-component -B build -DCMAKE_BUILD_TYPE=Release -DORIENT_NATIVE=OFF
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure --parallel 2
```

For the full local-data checks:

```sh
python3 orient-endgame-component/tools/download_tablebases.py --verify-only
ORIENT_SYZYGY_PATH="$PWD/orient-endgame-component/external/tablebases/syzygy/3-4-5" \
  ctest --test-dir build --output-on-failure --parallel 2
ORIENT_REFEREE_BINARY="$PWD/build/orient-endgame-referee" \
ORIENT_SYZYGY_PATH="$PWD/orient-endgame-component/external/tablebases/syzygy/3-4-5" \
  python3 -m unittest discover -s orient-endgame-component/tests -p 'test_*.py'
```

Download tables first if absent, using `download_tablebases.py` without
`--verify-only`. Source-only testing intentionally skips the optional table
groups; a nested prepared-fixture check also skips its excluded archival data.

The accepted adaptive catalogue/prefix defaults and the fixed five-percent
performance gate are preserved. No decoder algorithm, training data, network
weights or external-engine labels were imported. The 007 measurements remain
historical evidence for their frozen source; the current fixes have not received
a new performance or strength claim. Larger-table probing, hostile/corrupt table
parsing and cross-platform execution have not been newly certified.

Original `BUNDLE-MANIFEST.json`, checkpoints and investigation evidence remain
local and unchanged. That manifest verifies a pristine original transfer, not
this source checkout. Later-source changes are documented here; raw original
evidence is deliberately outside the Git source selection. Local review failure
logs and patches are saved under repository-root `build/preupload-review/`.
