/* Diagnostic-only reader accounting; not an engine/UCI interface. */
#ifndef ORIENT_TB_DIAGNOSTICS_H
#define ORIENT_TB_DIAGNOSTICS_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
enum { ORIENT_TB_CATALOG = 0, ORIENT_TB_PATHS = 1, ORIENT_TB_PAIRS = 2 };
struct OrientTbAllocationStats {
  uint64_t live_bytes, peak_bytes, allocations, frees;
};
struct OrientTbDiagnostics {
  struct OrientTbAllocationStats allocations[3];
  uint64_t open_attempts, open_successes, open_failures;
  uint64_t map_calls, unmap_calls, mapped_bytes, peak_mapped_bytes;
  // Known mutable control/hash storage only. Excludes diagnostic ledgers and
  // read-only encoding/attack tables; use ELF sections for whole-binary totals.
  uint64_t static_bytes;
  unsigned piece_count, pawn_count, piece_capacity, pawn_capacity;
};
// Available only in an ORIENT_FATHOM_DIAGNOSTICS build. Caller serializes with
// initialization/probing/teardown; no locks or counters enter normal builds.
void orient_tb_diagnostics_snapshot(struct OrientTbDiagnostics *out);
#ifdef __cplusplus
}
#endif
#endif
