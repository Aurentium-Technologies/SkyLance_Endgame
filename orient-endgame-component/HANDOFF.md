# SkyLance source-checkout handoff

This document describes the GitHub checkout, not the original all-data transfer
bundle. Run every command below from the repository root. Start with the
[repository README](../README.md) for the public introduction.

## What the checkout includes

- `src/`, `include/` and `third_party/fathom/`: the original engine integration
  and attributed maintained Fathom reader.
- `tests/`, `tools/` and `CMakeLists.txt`: focused tests, downloader, provenance
  helpers and benchmark clients.
- `external/fathom-upstream/`: the unchanged, pinned MIT comparison reader.
- `docs/` and repository-root `evidence/`: reports and the public protocol,
  frozen-source and result records described in the evidence index.
- Branding, licence notices and the standalone optional Rust comparator client.

The checkout does **not** include Syzygy table files, compiled executables,
compiler caches, optional Shakmaty dependency checkouts, frozen engine checkpoints
or the original raw investigation directories. Tables are downloaded separately.
Large reproducibility assets are separate from the Git source tree; see the
[public evidence index](../evidence/README.md) for their manifests and availability.

## Build and run

Requirements: CMake 3.20+, C++20, Python 3.10+ for tests, and threading support.
The portable build is:

```sh
cmake -S orient-endgame-component -B build -DCMAKE_BUILD_TYPE=Release -DSKYLANCE_NATIVE=OFF
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure --parallel 2
./build/skylance --version
./build/skylance
```

`skylance` is the public executable and its UCI author is Aurentium Technologies.
`orient` remains a compatibility target. `SKYLANCE_*` CMake options map to the
retained `ORIENT_*` definitions; use one spelling for each option in a configure command. Reconfiguration
keeps the public and legacy cache values synchronized; conflicting initial values
are rejected. Internal
namespaces, the network-file format and research environment-variable names
remain compatible. Classical evaluation is the default; no weights are needed.

## Optional table data and full checks

The exact collection used has 145 WDL and 145 DTZ files, 983,957,920 bytes total,
covering three through five pieces including both kings. Its URLs, sizes and
SHA-256 values are pinned in [the catalogue](tools/syzygy345.json).

```sh
python3 orient-endgame-component/tools/download_tablebases.py
python3 orient-endgame-component/tools/download_tablebases.py --verify-only
ORIENT_SYZYGY_PATH="$PWD/orient-endgame-component/external/tablebases/syzygy/3-4-5" \
  ctest --test-dir build --output-on-failure --parallel 2
ORIENT_REFEREE_BINARY="$PWD/build/orient-endgame-referee" \
ORIENT_SYZYGY_PATH="$PWD/orient-endgame-component/external/tablebases/syzygy/3-4-5" \
  python3 -m unittest discover -s orient-endgame-component/tests -p 'test_*.py'
```

Configure your GUI's `SyzygyPath` to the absolute table directory. Without table
files the engine uses ordinary search and table-dependent tests report skips.
The archived prepared-game-fixture check also skips if its optional evidence is
absent; this is separate from the real table checks.

## Reader memory regressions and sanitizers

Two tiny, publisher-verified KQvK files exercise the teardown and path-list
regressions without downloading the complete collection:

```sh
python3 orient-endgame-component/tools/ci_tables.py
cmake -S orient-endgame-component -B build/sanitized -DCMAKE_BUILD_TYPE=Debug -DSKYLANCE_NATIVE=OFF -DSKYLANCE_SANITIZERS=ON
cmake --build build/sanitized --parallel 2
./build/sanitized/test_dynamic_catalog --regressions-only "$PWD/orient-endgame-component/external/tablebases/ci-regressions"
```

Missing data in this explicit regression mode fails rather than reporting a
skip. CI runs these cases with ASan/UBSan on every change. A separate
weekly/manual job verifies the full cached collection and runs full-data Release
and sanitizer checks. Cache hits are rehashed against the pinned catalogue.
Hosted full-data results must be checked independently of the normal push jobs.

## Research and source identity

Retained defaults are prefix acceleration and adaptive catalogue ON; fixed
five-piece catalogue, compact cache, root-legal reuse, profiling and diagnostic
instrumentation OFF. Runtime SyzygyCache defaults to zero. Keep table files
immutable during probing and preserve the fixed five-percent regression gates.

[Current-source confirmation 008](../evidence/tablebases-008/README.md) matched
exact answers but failed its unchanged performance gates. The result is preserved
and does not renew the historical speed claim.

[Investigation 007](docs/endgame-improvements-007.md) describes its historical
frozen source. Later reader teardown, path parsing and time-allocation fixes
change current source and binaries. Follow the [evidence index](../evidence/README.md)
for source bindings and subsequent measurements. Do not apply historical ratios
to a different source tree without measuring it.

A new campaign must freeze the actual candidate, tables, fixtures, tools and
compiler settings before inspecting results. The historical 007 reproducer
intentionally rebuilds historical snapshots. The new
`tools/reproduce_acceptance.py` accepts an explicit candidate and a new output
directory; its evidence-root prerequisites are documented with the evidence
archive. Never overwrite a historical run or extend trials to obtain a pass.
Run timing only while other heavy work is idle; the compute lease is per workspace.

## Original transfer archive

`BUNDLE-MANIFEST.json`, `PACKAGE-CONTENTS.json` and `reference/` are historical
provenance for the original transfer. Their inclusion lists do not describe this
Git checkout. `tools/verify_bundle.py` is only for a pristine, complete original
archive and is expected to reject edited or partial source checkouts. It is not
a current-source acceptance check. Downloaded table integrity is verified with
`download_tablebases.py --verify-only`; source revisions are identified by Git
and the frozen per-file campaign manifests.

Original archives and hash-bound records remain unchanged locally. Their
historical absolute paths are preserved; portable reproduction must record
relocation separately rather than silently rewrite the original evidence.
