cmake_minimum_required(VERSION 3.20)
project(SkyLanceEndgameComponent VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
option(ORIENT_NATIVE "Optimize for this CPU; resulting binaries are not portable" OFF)
option(ORIENT_SANITIZERS "Enable address and undefined-behaviour sanitizers" OFF)
option(ORIENT_TESTS "Build the focused endgame and integration checks" ON)
option(ORIENT_COMPACT_TABLEBASE_CACHE "Experimental eight-byte cache (not adopted)" OFF)
option(ORIENT_REUSE_ROOT_LEGAL "Experimental root legal-list reuse (not adopted)" OFF)
option(ORIENT_TABLEBASE_PROFILING "Instrument root phases; excluded from acceptance timing" OFF)
option(ORIENT_FATHOM_PREFIX_LENGTH "Retained exact Huffman prefix-length accelerator" ON)
option(ORIENT_FATHOM_FIVE_PIECE_CATALOG "Experimental five-piece catalogue (not adopted)" OFF)
option(ORIENT_FATHOM_DYNAMIC_CATALOG "Retained adaptive discovered-material catalogue" ON)
option(ORIENT_FATHOM_DIAGNOSTICS "Diagnostic-only reader allocation/discovery counters" OFF)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  add_compile_options(-Wall -Wextra -Wpedantic -Wshadow)
  if(ORIENT_NATIVE)
    add_compile_options(-march=native)
  endif()
  if(ORIENT_SANITIZERS)
    add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
    add_link_options(-fsanitize=address,undefined)
  endif()
endif()
find_package(Threads REQUIRED)

set_source_files_properties(third_party/fathom/src/tbprobe.c PROPERTIES LANGUAGE CXX)
add_library(orient_fathom STATIC third_party/fathom/src/tbprobe.c)
target_include_directories(orient_fathom PUBLIC third_party/fathom/src)
target_compile_definitions(orient_fathom PRIVATE TB_NO_HELPER_API
  ORIENT_FATHOM_PREFIX_LENGTH=$<BOOL:${ORIENT_FATHOM_PREFIX_LENGTH}>
  ORIENT_FATHOM_FIVE_PIECE_CATALOG=$<BOOL:${ORIENT_FATHOM_FIVE_PIECE_CATALOG}>
  ORIENT_FATHOM_DYNAMIC_CATALOG=$<BOOL:${ORIENT_FATHOM_DYNAMIC_CATALOG}>
  ORIENT_FATHOM_DIAGNOSTICS=$<BOOL:${ORIENT_FATHOM_DIAGNOSTICS}>)
target_link_libraries(orient_fathom PRIVATE Threads::Threads)

# These original Orient dependencies make reader/search integration buildable.
# No training generator, network weights or bot bridge is linked into these targets.
add_library(orient_core src/chess.cpp src/evaluation.cpp src/search.cpp src/nnue.cpp src/tablebases.cpp)
target_include_directories(orient_core PUBLIC include)
target_link_libraries(orient_core PUBLIC Threads::Threads PRIVATE orient_fathom)
target_compile_definitions(orient_core PUBLIC
  ORIENT_COMPACT_TABLEBASE_CACHE=$<BOOL:${ORIENT_COMPACT_TABLEBASE_CACHE}>
  ORIENT_REUSE_ROOT_LEGAL=$<BOOL:${ORIENT_REUSE_ROOT_LEGAL}>
  ORIENT_TABLEBASE_PROFILING=$<BOOL:${ORIENT_TABLEBASE_PROFILING}>)

# Keep the historical executable name for research scripts and saved commands.
# Public builds and installation use the SkyLance name.
foreach(engine_target IN ITEMS skylance orient)
  add_executable(${engine_target} src/main.cpp)
  target_compile_definitions(${engine_target} PRIVATE ORIENT_VERSION="${PROJECT_VERSION}")
  target_link_libraries(${engine_target} PRIVATE orient_core)
endforeach()
install(TARGETS skylance RUNTIME DESTINATION bin)

foreach(pair IN ITEMS
    "orient-tablebase-bench|benchmark_tablebases.cpp"
    "orient-tablebase-probe|tablebase_probe.cpp"
    "orient-reader-bench|benchmark_reader.cpp"
    "orient-endgame-referee|endgame_referee.cpp")
  string(REPLACE "|" ";" item "${pair}")
  list(GET item 0 target)
  list(GET item 1 source)
  add_executable(${target} tools/${source})
  target_link_libraries(${target} PRIVATE orient_core)
endforeach()
add_executable(orient-tablebase-ordered-probe tools/tablebase_probe.cpp)
target_compile_definitions(orient-tablebase-ordered-probe PRIVATE ORIENT_PRESERVE_TABLEBASE_ORDER)
target_link_libraries(orient-tablebase-ordered-probe PRIVATE orient_core)

# The measurement shim supplies one reader implementation and must use exactly
# the same feature definitions as the library; the static linker need not pull
# a second Fathom object from orient_fathom.
add_executable(orient-reader-compare tools/reader_compare.cpp tools/reader_compare_dtz.cpp)
target_include_directories(orient-reader-compare PRIVATE third_party/fathom/src)
target_compile_definitions(orient-reader-compare PRIVATE
  ORIENT_FATHOM_PREFIX_LENGTH=$<BOOL:${ORIENT_FATHOM_PREFIX_LENGTH}>
  ORIENT_FATHOM_FIVE_PIECE_CATALOG=$<BOOL:${ORIENT_FATHOM_FIVE_PIECE_CATALOG}>
  ORIENT_FATHOM_DYNAMIC_CATALOG=$<BOOL:${ORIENT_FATHOM_DYNAMIC_CATALOG}>
  ORIENT_FATHOM_DIAGNOSTICS=$<BOOL:${ORIENT_FATHOM_DIAGNOSTICS}>)
target_link_libraries(orient-reader-compare PRIVATE orient_core)

if(ORIENT_FATHOM_DIAGNOSTICS)
  if(NOT EXISTS "${CMAKE_SOURCE_DIR}/third_party/fathom/src/orient_tb_diagnostics.h")
    message(FATAL_ERROR "This source reader does not provide the diagnostic overlay")
  endif()
  add_executable(orient-reader-memory tools/benchmark_reader_memory.cpp)
  target_include_directories(orient-reader-memory PRIVATE third_party/fathom/src)
  target_compile_definitions(orient-reader-memory PRIVATE ORIENT_FATHOM_DIAGNOSTICS=1
    ORIENT_FATHOM_FIVE_PIECE_CATALOG=$<BOOL:${ORIENT_FATHOM_FIVE_PIECE_CATALOG}>
  ORIENT_FATHOM_DYNAMIC_CATALOG=$<BOOL:${ORIENT_FATHOM_DYNAMIC_CATALOG}>
    ORIENT_FATHOM_PREFIX_LENGTH=$<BOOL:${ORIENT_FATHOM_PREFIX_LENGTH}>)
  target_link_libraries(orient-reader-memory PRIVATE orient_core)
endif()

if(EXISTS "${CMAKE_SOURCE_DIR}/external/fathom-upstream/src/tbprobe.c")
  set_source_files_properties(external/fathom-upstream/src/tbprobe.c PROPERTIES LANGUAGE CXX)
  foreach(target IN ITEMS orient-tablebase-reference orient-tablebase-reference-ordered)
    add_executable(${target} tools/tablebase_probe.cpp src/chess.cpp
      external/fathom-upstream/src/tbprobe.c)
    target_include_directories(${target} PRIVATE include external/fathom-upstream/src)
    target_compile_definitions(${target} PRIVATE ORIENT_REFERENCE_READER TB_NO_HELPER_API)
    target_link_libraries(${target} PRIVATE Threads::Threads)
  endforeach()
  target_compile_definitions(orient-tablebase-reference-ordered PRIVATE ORIENT_PRESERVE_TABLEBASE_ORDER)
endif()

if(ORIENT_TESTS)
  enable_testing()
  add_executable(test_dynamic_catalog tests/test_dynamic_catalog.cpp)
  target_include_directories(test_dynamic_catalog PRIVATE third_party/fathom/src)
  target_link_libraries(test_dynamic_catalog PRIVATE Threads::Threads)
  add_test(NAME dynamic_catalog COMMAND test_dynamic_catalog)
  set_tests_properties(dynamic_catalog PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60)
  foreach(word_size IN ITEMS 64 32)
    add_executable(test_fathom_prefix${word_size} tests/test_fathom_prefix.cpp)
    target_include_directories(test_fathom_prefix${word_size} PRIVATE third_party/fathom/src)
    target_compile_definitions(test_fathom_prefix${word_size} PRIVATE TB_NO_HELPER_API
      ORIENT_FATHOM_PREFIX_LENGTH=1
      ORIENT_FATHOM_FIVE_PIECE_CATALOG=$<BOOL:${ORIENT_FATHOM_FIVE_PIECE_CATALOG}>
  ORIENT_FATHOM_DYNAMIC_CATALOG=$<BOOL:${ORIENT_FATHOM_DYNAMIC_CATALOG}>)
    if(word_size EQUAL 32)
      target_compile_definitions(test_fathom_prefix${word_size} PRIVATE ORIENT_FATHOM_FORCE_DECOMP32=1)
    endif()
    target_link_libraries(test_fathom_prefix${word_size} PRIVATE Threads::Threads)
    add_test(NAME fathom_prefix${word_size} COMMAND test_fathom_prefix${word_size})
    set_tests_properties(fathom_prefix${word_size} PROPERTIES TIMEOUT 60)
  endforeach()
  if(EXISTS "${CMAKE_SOURCE_DIR}/third_party/fathom/src/orient_tb_diagnostics.h")
    add_executable(test_fathom_catalog tests/test_fathom_catalog.cpp)
    target_include_directories(test_fathom_catalog PRIVATE third_party/fathom/src)
    target_compile_definitions(test_fathom_catalog PRIVATE TB_NO_HELPER_API
      ORIENT_FATHOM_DIAGNOSTICS=1 ORIENT_FATHOM_FIVE_PIECE_CATALOG=1 ORIENT_FATHOM_PREFIX_LENGTH=1)
    target_link_libraries(test_fathom_catalog PRIVATE Threads::Threads)
    add_test(NAME fathom_catalog COMMAND test_fathom_catalog)
    set_tests_properties(fathom_catalog PROPERTIES TIMEOUT 120)
  endif()
  if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    add_executable(test_fathom_map_failure tests/test_fathom_map_failure.cpp)
    target_include_directories(test_fathom_map_failure PRIVATE third_party/fathom/src)
    target_compile_definitions(test_fathom_map_failure PRIVATE TB_NO_HELPER_API
      ORIENT_FATHOM_PREFIX_LENGTH=$<BOOL:${ORIENT_FATHOM_PREFIX_LENGTH}>
      ORIENT_FATHOM_FIVE_PIECE_CATALOG=$<BOOL:${ORIENT_FATHOM_FIVE_PIECE_CATALOG}>
  ORIENT_FATHOM_DYNAMIC_CATALOG=$<BOOL:${ORIENT_FATHOM_DYNAMIC_CATALOG}>)
    target_link_libraries(test_fathom_map_failure PRIVATE Threads::Threads)
    add_test(NAME tablebase_map_failure COMMAND test_fathom_map_failure)
    set_tests_properties(tablebase_map_failure PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 30)
  endif()
  foreach(pair IN ITEMS
      "test_tablebase_cache|tablebase_cache_identity"
      "test_tablebases|tablebase_adapter"
      "test_endgame_search|endgame_search"
      "test_chess|chess_core"
      "test_search|search"
      "test_search_internal|search_pruning_regression")
    string(REPLACE "|" ";" item "${pair}")
    list(GET item 0 target)
    list(GET item 1 test_name)
    add_executable(${target} tests/${target}.cpp)
    target_link_libraries(${target} PRIVATE orient_core)
    add_test(NAME ${test_name} COMMAND ${target})
    set_tests_properties(${test_name} PROPERTIES TIMEOUT 180)
  endforeach()
  set_tests_properties(endgame_search PROPERTIES SKIP_RETURN_CODE 77)
  if(ORIENT_FATHOM_DIAGNOSTICS)
    add_test(NAME reader_memory_parser COMMAND orient-reader-memory --selftest)
    set_tests_properties(reader_memory_parser PROPERTIES TIMEOUT 30)
  endif()

  find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)
  foreach(pair IN ITEMS
      "checkpoint_reproduction|test_checkpoint.py"
      "reader_memory_gates|test_reader_memory.py"
      "reader_memory_verification|test_reader_memory_verification.py"
      "reader_comparison_gates|test_reader_comparison.py"
      "reader_comparison_semantics|test_reader_comparison_semantics.py"
      "reader_optimization_gates|test_reader_optimization.py"
      "tablebase_optimization_gates|test_tablebase_optimization.py"
      "tablebase_download|test_tablebase_download.py"
      "endgame_playing_fixtures|test_endgame_playing_fixtures.py"
      "endgame_playing_audit|test_endgame_playing_audit.py")
    string(REPLACE "|" ";" item "${pair}")
    list(GET item 0 test_name)
    list(GET item 1 source)
    add_test(NAME ${test_name} COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/${source})
    set_tests_properties(${test_name} PROPERTIES TIMEOUT 60)
  endforeach()
  add_test(NAME tablebase_uci COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_SOURCE_DIR}/tools/test_tablebase_uci.py $<TARGET_FILE:skylance>)
  set_tests_properties(tablebase_uci PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60)
  add_test(NAME uci_lifecycle COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_SOURCE_DIR}/tools/test_uci.py $<TARGET_FILE:skylance>)
  set_tests_properties(uci_lifecycle PROPERTIES TIMEOUT 60)
  add_test(NAME endgame_playing_referee COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_SOURCE_DIR}/tests/test_endgame_referee.py $<TARGET_FILE:orient-endgame-referee>)
  set_tests_properties(endgame_playing_referee PROPERTIES TIMEOUT 60)
endif()
