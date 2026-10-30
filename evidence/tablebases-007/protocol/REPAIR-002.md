# Run 002 preflight repair

Run001 started no measurements. Its compile-command validator incorrectly included the standalone diagnostic-only catalogue unit test in native timing instrumentation checks. Run002 excludes test translation units and still checks all production and measurement translation units, plus explicit native reader/DTZ-shim and diagnostic reader/memory-shim definitions. No compiler, binary, corpus, workload, repeats, thresholds or source algorithms changed. The exact-answer proof remains applicable. Both failed preflight and original controller are preserved.
