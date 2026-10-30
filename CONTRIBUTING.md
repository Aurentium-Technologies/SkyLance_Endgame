# Contributing to SkyLance

Open an issue describing a reproducible problem or proposed improvement before a
large change. Include the source revision, compiler/OS, UCI commands or minimal
FEN/history transcript, expected result and actual result. Keep credentials and
machine-specific configuration out of reports.

## Build and test

Use the commands in the [README](README.md) and [source handoff](orient-endgame-component/HANDOFF.md).
CTest registers the Python unit modules as well as native and UCI checks.
For reader changes, run the tiny real-data sanitizer regressions. For search or
adapter changes, also run full-table checks and retain repetition/rule-50 tests.
A source-only pass does not establish full-table or sanitizer coverage.

Downloaded tables, build outputs, caches and raw campaigns stay outside Git.
Do not alter third-party notices, original hash-bound snapshots or historical
results. Keep Fathom fork hashes and sequential patches current when modifying
its source. Preserve existing option spellings and file formats unless a
migration is explicitly agreed.

## Performance and claims

Freeze baseline and candidate source, binary hashes, fixtures, data catalogue,
compiler settings and protocol before timing. Keep the five-percent regression
gates and exact chess-answer checks. Use new output directories, preserve failed
runs, and report the measured source rather than assuming a result applies to
HEAD. Do not rerun or extend a campaign merely to obtain a pass.

External engines and readers are attributed measurement references. Do not
import engine code, weights, evaluation labels or training moves into original
SkyLance search/evaluation. Tablebase reader ancestry remains attributed.
Small matches or local speed ratios do not establish an Elo rating or a
roster-wide fastest-reader claim.

Changes should explain the problem, resulting behavior, verification and any
limits. Add focused regression tests for actual bugs; avoid tests that only
repeat implementation details.
