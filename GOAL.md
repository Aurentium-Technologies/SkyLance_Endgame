# Endgame component research

The [pre-upload code review and bug fixes, 30 October 2026](orient-endgame-component/docs/preupload-review-2026-10-30.md) record the current SkyLance source, validation and publication boundaries.

The component continuation instructions are in [orient-endgame-component/GOAL.md](orient-endgame-component/GOAL.md) and [HANDOFF.md](orient-endgame-component/HANDOFF.md).

The completed [GitHub systems and benchmark comparison, checked 29 October 2026](research/github-comparison-2026-10-29/comparison.md) records the retained system, controlled Shakmaty results, other public benchmarks, correctness limits and a fresh audit of the packaged evidence. It introduces no engine change or new timed benchmark. Original packaged files were unchanged at that stage; later implementation changes are recorded in 007.

The completed [exact-five-piece comparison 006](orient-endgame-component/docs/endgame-reader-comparison-006.md), measured 30 October 2026, contains 540 primary samples over 30 balanced blocks. Thirteen of fifteen comparisons pass the frozen five-percent elapsed-time and p95 gates. DTZ and complete-root queries pass against all five readers; WDL versus Fathom and Pyrrhic C is inconclusive at the required margin. The roster-wide claim is not established. [Protocol and reproduction guide](orient-endgame-component/artifacts/investigations/tablebases-006/README.md). No production algorithm or new candidate was adopted.

The completed [endgame improvements 007](orient-endgame-component/docs/endgame-improvements-007.md) fix the recorded repetition-history draw loss and adopt the adaptive catalogue after a fixed before/after campaign. Table configuration measured 40% faster, requested reader metadata fell 1.9 MiB, WDL measured 7–12% faster, and every declared regression gate passed. Direct WDL prototypes that slowed queries were rejected. The original transfer manifest, checkpoints and investigations 001–006 remain preserved; current source/default/handoff changes have new 007 provenance. [Reproduction and raw evidence](orient-endgame-component/artifacts/investigations/tablebases-007/README.md).
