# SkyLance endgame-reader continuation handoff

Current source checkout: see the [repository build instructions](../README.md) and
[pre-upload review](docs/preupload-review-2026-10-30.md). The public executable is
`skylance`, with UCI author Aurentium Technologies. The `orient` executable remains
available for historical research commands. The fixes after 007 mean newly built
binaries differ from accepted 007 binaries. Performance measurements below belong
to the frozen 007 campaign and have not been rerun for this review.

The Git source checkout excludes `external/tablebases/`, optional Rust comparison
dependencies and `artifacts/`; those remain local. Download tables with
`python3 tools/download_tablebases.py` if desired. The basic C++ build works without
them. The original bundle verification described below applies
only to a pristine, complete transfer archive, not the edited source checkout.

Prepared 29 October 2026; updated 30 October 2026 after investigation 007. The original source/package reference and investigations 001–006 are preserved. Current component source now includes the accepted007 changes.

Latest result: [improvements 007](docs/endgame-improvements-007.md). The recorded drawing-root history loss is fixed. Adaptive catalogue allocation is ON after passing all declared correctness/memory/startup/regression gates. The retained executable is `build/release/orient`. Table readiness measured 40% faster, reader metadata 1.9 MiB smaller, and WDL 7–12% faster on the two declared corpora. These local ratios do not update006 competitor-confidence claims or establish Elo.

## Start here

This folder contains the reader and enough of Orient's original local engine to build it, exercise UCI integration and run meaningful reader/search tests. It works from its extracted location; the basic build, integrity verification and probes require no original project folder, credentials, network service or download.

Prerequisites: CMake 3.20+, a C++20 compiler, Python 3.10+ and standard threading support. The archive verification was exercised with GNU C++ 13.3.0 on Linux. Rebuild from source for another machine; historical native binaries are provenance/reference files.

From this folder:

```sh
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release
cmake --build build/release -j3
ORIENT_SYZYGY_PATH="$PWD/external/tablebases/syzygy/3-4-5" ctest --test-dir build/release --output-on-failure
./build/release/skylance --version
```

`skylance` is the public UCI executable. Its `SyzygyPath` starts empty; configure the table directory when using it interactively. Set the test environment variable shown above only when those tables are installed; omit it for the source-only checks. The focused suite omits extended perft by default; `./build/release/test_chess --extended` and `--extended-direct` remain available separately.

`python3 tools/verify_bundle.py` validates a pristine transfer archive against BUNDLE-MANIFEST.json and independently validates its tables against the publisher catalogue. It is expected to fail on this edited checkout and must not be used as its current-source acceptance check. Retain the original tar.gz and checksum as the pristine reference. To verify downloaded table data independently, run `python3 tools/download_tablebases.py --verify-only`.

## Retained state and findings

- Retain accepted 016 prefix behavior plus 007 adaptive catalogue. `ORIENT_FATHOM_PREFIX_LENGTH` and `ORIENT_FATHOM_DYNAMIC_CATALOG` are ON; `ORIENT_FATHOM_FIVE_PIECE_CATALOG` and `ORIENT_FATHOM_DIAGNOSTICS` stay OFF. Compact WDL cache and root-legal-reuse experiments also remain OFF; runtime SyzygyCache defaults to zero.
- Five pieces includes both kings and pawns. The 290 ordinary local WDL/DTZ files total 983,957,920 bytes; the unchanged dataset manifest and publisher SHA-256 catalogue are included. Files stay on disk and immutable during probing.
- Experiment 003 retained the exact prefix-length accelerator. Experiment 004 measured faster Orient query stacks than pinned shakmaty on the recorded warm-cache workloads; it did not establish a pure decoder, whole-engine or Elo ranking.
- Experiment 005 saved 1,966,592 requested reader-allocation bytes and reduced constructor/configured-readiness times by 71.56% / 44.14%. It failed the five-percent speed-regression gate, including held-out DTZ +22.97%. The catalogue prototype remains disabled. No Orient 017 checkpoint exists.
- The prototype preserves measured outcomes, DTZ, suggestions and native alternatives. Its four original verification configurations passed 136 groups. That is historical project evidence; the newly extracted component suite has a focused, smaller test inventory.
- Reader-owned requested payload, allocator bookkeeping, mapped-file virtual size and resident table pages are different measurements. Mappings persist after adapter destruction under the existing singleton lifetime; explicit reader teardown releases them. The metadata experiment does not impose a hard RSS limit.
- Investigation007 fixes the demonstrated playing diagnostic 001 record 53/ply37 loss using full-history certified draw guidance at strict WDL2 roots. Keep all repetition-aware TT/null/rule-50 safeguards. Decisive and uncertain history-sensitive roots still use ordinary search; arbitrary-history perfection is not claimed.

Read these reports in order as needed:

1. [Integration and boundary](docs/endgame-tablebases-implementation-2026-10-27.md)
2. [Retained prefix optimization](docs/endgame-reader-optimization-003.md)
3. [Shakmaty comparison](docs/endgame-reader-comparison-004.md)
4. [Latest memory/startup result](docs/endgame-reader-memory-005.md)
5. [Latest accepted improvements](docs/endgame-improvements-007.md)
6. [Full-history playing diagnostic](docs/endgame-playing-001-2026-10-28.md)

## What is included

- `third_party/fathom/`: maintained local MIT reader fork, original licence, upstream pin, fork record and reproducible patches.
- `src/` and `include/orient/`: original board, evaluation, NNUE-loading support, adapter and UCI integration plus the documented007 search fix needed for standalone builds. No network weights are included; classical evaluation remains the default. No training executable or bot target is exposed by this package.
- `tools/` and `tests/`: reader/tablebase probes, benchmarks, diagnostics, provenance/correctness controllers, UCI helpers and relevant regressions.
- `external/tablebases/syzygy/3-4-5/`: complete verified ordinary table files and relative-root manifest.
- `external/fathom-upstream/`: untouched pinned upstream comparison source.
- `external/reader-comparison/shakmaty/`, the isolated Rust client and public Cargo registry cache: optional external comparator source/dependencies, with GPL COPYING and lockfile. They are not linked into Orient or used for training.
- `artifacts/investigations/tablebases-001` through `007`: curated reader research, fixtures, source snapshots, raw positive/negative measurements and audits. Generated compiler build trees are omitted.
- `artifacts/endgame-playing-001/`: PGN, full trace, fixtures and diagnosis for the known history issue.
- Frozen 015/016 reference checkpoint directories, including their immutable source archives, licence/provenance manifests and historical binaries. These historical archives retain wider original-project source for reproducibility.

No live bot configuration, token files, SSH keys, network weights, training corpus, Rust toolchain or unrelated match campaigns are packaged. Current source selection and exclusions are recorded in PACKAGE-CONTENTS.json.

## Continuing research safely

Use a new investigation directory and preserve the shipped evidence. Rebuild baseline and candidate from pinned source under identical settings before new timings; benchmark builds should use the same native flag, cache and profiling settings. Keep all chess outcomes exact and the existing five-percent regression limit unless the owner explicitly changes that decision. No compression, eviction, training or live-play change has been adopted. The narrow 007 drawing-root policy is documented with its proof and full-history regressions.

For the optional memory diagnostic only:

```sh
cmake -S . -B build/diagnostics -DCMAKE_BUILD_TYPE=Release -DORIENT_NATIVE=ON -DORIENT_FATHOM_DIAGNOSTICS=ON -DORIENT_FATHOM_DYNAMIC_CATALOG=ON -DORIENT_FATHOM_FIVE_PIECE_CATALOG=OFF
cmake --build build/diagnostics --target orient-reader-memory -j3
./build/diagnostics/orient-reader-memory "$PWD/external/tablebases/syzygy/3-4-5" artifacts/investigations/tablebases-005/fixtures/continuity-shared-valid.fen
```

Those counters are diagnostic overhead and must be OFF for timing acceptance. Keep a separate uninstrumented timing build. The adaptive catalogue is retained after 007; the old fixed five-piece catalogue stays disabled. To reproduce 005 explicitly turn adaptive OFF before turning fixed five-piece ON.

Historical JSON manifests and saved scripts deliberately retain their original absolute paths and hashes. They are evidence, not ready-to-run configurations for this new location. Do not edit originals in place or blindly replace path strings inside signed/hash-bound records. Rebuild the required executables, then create fresh configurations with paths and SHA-256 hashes from this extracted project. The package's relative BUNDLE-MANIFEST.json is the authority for pristine transfer integrity. After007 use its retained-source/preservation manifests for the intentional source changes. Some preserved report cross-links refer to the wider original project.

The compute lease in tools/experiment.py is per workspace. Ensure other project experiments are idle before measuring performance here. The packaging verification does not rerun games, a rating campaign or acceptance timings.

The optional Rust comparator requires Rust 1.97 or newer. The 592 MiB local toolchain is omitted; use an installed compatible toolchain. Its public registry dependencies are included, allowing an offline build when Rust is already available:

```sh
CARGO_HOME="$PWD/external/cargo-cache" cargo build --release --locked --offline --manifest-path tools/shakmaty_reader_compare/Cargo.toml
```

That optional dependency is separate from the C++ reader build. Retain all included MIT/GPL and dependency licence notices. Solved-position data and external reader code remain explicitly attributed; Orient's own search/evaluation and primary move generation remain original.
