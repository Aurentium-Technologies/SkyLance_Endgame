// Measurement-only access to the existing Fathom DTZ primitive. The linked
// implementation is the pinned reader, including Orient's adopted prefix hint.
// It is not linked into the production engine or used for training.
#ifndef TB_NO_HELPER_API
#define TB_NO_HELPER_API
#endif
#ifndef ORIENT_FATHOM_PREFIX_LENGTH
#define ORIENT_FATHOM_PREFIX_LENGTH 1
#endif
#include "../third_party/fathom/src/tbprobe.c"

extern "C" int orient_comparison_dtz(const uint64_t* board_bits,
                                      unsigned halfmove, unsigned ep,
                                      bool white_to_move, int* success) {
    Pos pos = {board_bits[0], board_bits[1], board_bits[2], board_bits[3],
               board_bits[4], board_bits[5], board_bits[6], board_bits[7],
               uint8_t(halfmove), uint8_t(ep), white_to_move};
    if (!is_valid(&pos)) {
        *success = 0;
        return 0;
    }
    return probe_dtz(&pos, success);
}
