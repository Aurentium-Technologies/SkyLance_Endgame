# Changelog

## 0.1.0 research preview — 2026-10-31

- Publish auditable benchmark records and separate reproducibility assets while
  keeping solved-position table files outside Git.
- Add per-change real-data ASan/UBSan reader regressions, Linux GCC/Clang and
  macOS builds, plus weekly/manual cached full-table checks.
- Make the source-checkout handoff consistent with the README and distinguish
  historical transfer manifests from current source verification.
- Add public `SKYLANCE_*` CMake aliases while retaining `ORIENT_*` compatibility.
- Add explicit-current-source acceptance tooling with frozen source manifests;
  exact answers matched in 008, but the fixed performance gates failed. Preserve
  the complete unfavourable result and do not renew historical speed claims.

## Initial source publication — 2026-10-30

- Publish SkyLance source under Aurentium Technologies branding, with the MIT
  licence and separate third-party notices.
- Fix reader teardown use-after-free, trailing-separator path parsing, direct-API
  clock overflow, comparison false-pass paths and checkpoint/test tooling.
- Retain the accepted adaptive catalogue and prefix accelerator defaults.
- Exclude table files, builds, caches and raw investigation artifacts from Git;
  provide the pinned table downloader and publisher checksum catalogue.

The engine source reports version 0.1.0. Version text alone does not identify a
published release or certify engine strength; use a tag/commit and its evidence.
