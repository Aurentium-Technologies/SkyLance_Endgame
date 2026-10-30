# Standalone shakmaty-syzygy comparison client

This GPL-3.0-or-later measurement program is isolated from Orient. It is not linked into the C++ engine, used for training, or used during play. Its path dependencies refer to the pinned public shakmaty checkout under `external/reader-comparison/shakmaty`; see investigation `tablebases-004/shakmaty-pin.json`. Preserve the upstream COPYING file and Cargo.lock when sharing/rebuilding the client.

Build with Rust 1.97 or newer, release optimizations, native CPU targeting and no LTO. Investigation 004 used a workspace-local verified Rust 1.97.0 runtime and an offline, checksum-locked Cargo cache. The full flags and compiler/source/binary provenance are saved in `artifacts/investigations/tablebases-004/`.

CLI: `BINARY TABLEPATH CORPUS MODE REPEATS BACKEND`, where MODE is `wdl`, `dtz`, `all_moves` or `verify`; BACKEND is `mmap` or `pread`. Use the controller `tools/measure_reader_comparison.py` with its frozen JSON configuration rather than comparing arbitrary calls. The mmap client requires immutable local table files throughout each process.

`all_moves` is a comparison envelope that evaluates every legal child, with Fathom-equivalent nominal DTZ/clock conventions. It is not shakmaty's native best-move routine. Recommendations and rounded-DTZ metadata appear only in verification diagnostics. Read the measurement protocol and report before interpreting ratios or memory figures.
