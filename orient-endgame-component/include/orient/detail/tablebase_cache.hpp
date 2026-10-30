#pragma once

#include "orient/chess.hpp"
#include <bit>
#include <cstdint>
#include <optional>

namespace orient::detail {

using PackedTablebaseEntry = std::uint64_t;
static_assert(sizeof(PackedTablebaseEntry) == 8);

inline constexpr std::uint64_t TablebaseIdentityMask = (std::uint64_t{1} << 52) - 1;
inline constexpr std::uint64_t TablebaseValidBit = std::uint64_t{1} << 55;
inline constexpr std::uint64_t TablebaseEntryMask = (std::uint64_t{1} << 56) - 1;

// Exact identity for a consistent Orient position with two kings and at most
// three other pieces. This is not a hash. Its 52 bits, low to high, are:
// WK square(6), BK square(6), side(1), EP code(7), extra count(2), and three
// square(6)/type(3)/colour(1) records in ascending square order. EP code zero
// means absent; otherwise it is square+1. Unused records are zero.
//
// The raw-WDL caller must retain its no-castling/fresh-halfmove eligibility
// checks and game-history handling. Those fields are intentionally not encoded.
// The position's redundant bitboards/board must agree, as they do for all
// positions produced by Orient's parser and reversible rules routines.
inline std::optional<std::uint64_t> pack_tablebase_identity(const Position& p) noexcept {
    if ((p.side != White && p.side != Black) || p.ep < -1 || p.ep >= 64) return std::nullopt;
    const auto white_king = p.bb[White][King], black_king = p.bb[Black][King];
    if (!std::has_single_bit(white_king) || !std::has_single_bit(black_king)
        || (white_king & black_king) || (p.occupied[White] & p.occupied[Black])
        || (white_king & p.occupied[White]) != white_king
        || (black_king & p.occupied[Black]) != black_king) return std::nullopt;
    const int wk = std::countr_zero(white_king), bk = std::countr_zero(black_king);
    if (p.board[wk] != piece(White, King) || p.board[bk] != piece(Black, King)) return std::nullopt;
    auto extras = p.occupancy() & ~(white_king | black_king);
    const int count = std::popcount(extras);
    if (count > 3) return std::nullopt;
    std::uint64_t identity = std::uint64_t(wk) | (std::uint64_t(bk) << 6)
        | (std::uint64_t(p.side) << 12) | (std::uint64_t(p.ep + 1) << 13)
        | (std::uint64_t(count) << 20);
    unsigned index = 0;
    while (extras) {
        const int square = std::countr_zero(extras);
        extras &= extras - 1;
        const int raw = p.board[square];
        const auto type = type_of(raw);
        if (raw == 0 || type < Pawn || type > Queen) return std::nullopt;
        const auto color = color_of(raw);
        if (!(p.occupied[color] & bit(square)) || !(p.bb[color][type] & bit(square)))
            return std::nullopt;
        const std::uint64_t record = std::uint64_t(square) | (std::uint64_t(type) << 6)
            | (std::uint64_t(color) << 9);
        identity |= record << (22 + 10 * index++);
    }
    return identity;
}

inline PackedTablebaseEntry make_tablebase_entry(std::uint64_t identity, int wdl) noexcept {
    if ((identity & ~TablebaseIdentityMask) || wdl < 0 || wdl > 4) return 0;
    return identity | (std::uint64_t(wdl) << 52) | TablebaseValidBit;
}

inline int tablebase_entry_wdl(PackedTablebaseEntry entry) noexcept {
    if (!(entry & TablebaseValidBit) || (entry & ~TablebaseEntryMask)) return -1;
    const int wdl = int((entry >> 52) & 7);
    return wdl <= 4 ? wdl : -1;
}

inline bool tablebase_entry_matches(PackedTablebaseEntry entry, std::uint64_t identity) noexcept {
    return !(identity & ~TablebaseIdentityMask) && tablebase_entry_wdl(entry) >= 0
        && (entry & TablebaseIdentityMask) == identity;
}

} // namespace orient::detail
