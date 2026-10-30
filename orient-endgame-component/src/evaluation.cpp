#include "orient/search.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cstdlib>

namespace orient {
namespace {
constexpr std::array<int, 7> MidValue{0, 100, 325, 335, 505, 970, 0};
constexpr std::array<int, 7> EndValue{0, 120, 305, 330, 525, 940, 0};
constexpr std::array<int, 7> Phase{0, 0, 1, 1, 2, 4, 0};
constexpr std::array<int, 7> ExchangeValue{0, 100, 325, 335, 505, 970, 20000};
int pop(Bitboard& b) { const int s = std::countr_zero(b); b &= b - 1; return s; }

struct ExchangeBoard {
    std::array<std::array<Bitboard, 7>, 2> pieces;
    Bitboard occupied;
    std::array<int, 2> kings;
    bool attacked(int sq, Color by) const {
        return (pawn_attacks(opposite(by), sq) & pieces[by][Pawn])
            || (knight_attacks(sq) & pieces[by][Knight])
            || (king_attacks(sq) & pieces[by][King])
            || (bishop_attacks(sq, occupied) & (pieces[by][Bishop] | pieces[by][Queen]))
            || (rook_attacks(sq, occupied) & (pieces[by][Rook] | pieces[by][Queen]));
    }
    void capture(Color by, PieceType attacker, int from, int to,
                 PieceType victim, PieceType promoted) {
        pieces[opposite(by)][victim] &= ~bit(to);
        pieces[by][attacker] &= ~bit(from);
        pieces[by][promoted] |= bit(to);
        occupied &= ~bit(from);
        if (attacker == King) kings[by] = to;
    }
};
}

int evaluate(const Position& p) {
    std::array<int, 2> mid{}, end{};
    int phase = 0;
    const Bitboard all = p.occupancy();
    std::array<Bitboard, 2> pawn_control{};
    for (Color c : {White, Black}) {
        Bitboard pawns = p.bb[c][Pawn];
        while (pawns) pawn_control[c] |= pawn_attacks(c, pop(pawns));
    }
    for (Color c : {White, Black}) {
        const Color enemy = opposite(c);
        std::array<int, 8> files{};
        Bitboard pawns = p.bb[c][Pawn];
        while (pawns) ++files[file_of(pop(pawns))];
        for (int f = 0; f < 8; ++f) {
            if (files[f] > 1) {
                mid[c] -= 13 * (files[f] - 1);
                end[c] -= 20 * (files[f] - 1);
            }
        }
        for (int type = Pawn; type <= King; ++type) {
            const auto pt = PieceType(type);
            Bitboard pieces = p.bb[c][pt];
            phase += Phase[pt] * std::popcount(pieces);
            while (pieces) {
                const int sq = pop(pieces), f = file_of(sq);
                const int r = c == White ? rank_of(sq) : 7 - rank_of(sq);
                const int central = 14 - std::abs(2 * f - 7) - std::abs(2 * r - 7);
                mid[c] += MidValue[pt]; end[c] += EndValue[pt];
                switch (pt) {
                case Pawn: {
                    mid[c] += 5 * r + 2 * (7 - std::abs(2 * f - 7));
                    end[c] += 10 * r + central;
                    if ((f == 0 || files[f - 1] == 0) && (f == 7 || files[f + 1] == 0)) {
                        mid[c] -= 12; end[c] -= 10;
                    }
                    bool passed = true;
                    Bitboard opponents = p.bb[enemy][Pawn];
                    while (opponents) {
                        const int other = pop(opponents);
                        if (std::abs(file_of(other) - f) <= 1
                            && (c == White ? rank_of(other) > rank_of(sq) : rank_of(other) < rank_of(sq))) {
                            passed = false; break;
                        }
                    }
                    if (passed) { mid[c] += 2 * r * r; end[c] += 5 * r * r; }
                    if (pawn_control[c] & bit(sq)) { mid[c] += 7; end[c] += 9; }
                    break;
                }
                case Knight: mid[c] += 5 * central - (r == 0 ? 18 : 0); end[c] += 4 * central; break;
                case Bishop: mid[c] += 3 * central + 2 * r; end[c] += 3 * central; break;
                case Rook:
                    mid[c] += 2 * r + central; end[c] += 2 * central;
                    if (!files[f]) {
                        mid[c] += 15;
                        bool enemy_pawn = false;
                        Bitboard ep = p.bb[enemy][Pawn];
                        while (ep) if (file_of(pop(ep)) == f) enemy_pawn = true;
                        if (!enemy_pawn) mid[c] += 10;
                    }
                    break;
                case Queen: mid[c] += central; end[c] += 2 * central; break;
                case King: mid[c] -= 4 * central + 5 * r; end[c] += 6 * central; break;
                default: break;
                }
                if (pt >= Knight && pt <= Queen) {
                    const Bitboard mobility = attacks_from(pt, c, sq, all) & ~p.occupied[c] & ~pawn_control[enemy];
                    constexpr std::array<int, 7> mw{0, 0, 4, 4, 2, 1, 0};
                    constexpr std::array<int, 7> ew{0, 0, 3, 4, 4, 2, 0};
                    mid[c] += mw[pt] * std::popcount(mobility);
                    end[c] += ew[pt] * std::popcount(mobility);
                }
            }
        }
        if (std::popcount(p.bb[c][Bishop]) >= 2) { mid[c] += 28; end[c] += 40; }
        const int king = p.king_square(c);
        const Bitboard ring = king_attacks(king) | bit(king);
        int pressure = 0;
        for (int type = Knight; type <= Queen; ++type) {
            Bitboard attackers = p.bb[enemy][type];
            while (attackers) {
                const int sq = pop(attackers);
                constexpr std::array<int, 7> weights{0, 0, 3, 3, 4, 5, 0};
                pressure += weights[type] * std::popcount(attacks_from(PieceType(type), enemy, sq, all) & ring);
            }
        }
        mid[c] -= 2 * pressure;
        const int kf = file_of(king), kr = rank_of(king);
        for (int f = std::max(0, kf - 1); f <= std::min(7, kf + 1); ++f) {
            bool shelter = false;
            for (int distance = 1; distance <= 2; ++distance) {
                const int r = kr + (c == White ? distance : -distance);
                if (r >= 0 && r < 8 && (p.bb[c][Pawn] & bit(r * 8 + f))) shelter = true;
            }
            if (shelter) mid[c] += 12;
            else mid[c] -= 10;
        }
    }
    phase = std::min(24, phase);
    const int white = ((mid[White] - mid[Black]) * phase
                     + (end[White] - end[Black]) * (24 - phase)) / 24;
    return std::clamp((p.side == White ? white : -white) + 8, -20000, 20000);
}

int static_exchange(const Position& p, Move m) {
    if (!m || m.has(Move::Castle)) return 0;
    const int moving = p.board[m.from()];
    if (!moving) return 0;
    const Color us = color_of(moving);
    const PieceType attacker = type_of(moving);
    const int captured_sq = m.has(Move::EnPassant) ? m.to() + (us == White ? -8 : 8) : m.to();
    const PieceType victim = type_of(p.board[captured_sq]);
    const PieceType promoted = m.promotion() == Empty ? attacker : m.promotion();
    std::array<int, 32> gain{};
    gain[0] = ExchangeValue[victim] + ExchangeValue[promoted] - ExchangeValue[attacker];
    ExchangeBoard board{p.bb, p.occupancy(), {p.king_square(White), p.king_square(Black)}};
    if (m.has(Move::EnPassant)) {
        board.pieces[opposite(us)][Pawn] &= ~bit(captured_sq);
        board.occupied &= ~bit(captured_sq);
    }
    board.capture(us, attacker, m.from(), m.to(), m.has(Move::EnPassant) ? Empty : victim, promoted);
    board.occupied |= bit(m.to());
    Color turn = opposite(us);
    PieceType on_target = promoted;
    int depth = 0;
    while (depth < 31 && on_target != King) {
        bool found = false;
        ExchangeBoard chosen = board;
        PieceType next_target = Empty;
        for (int type = Pawn; type <= King && !found; ++type) {
            Bitboard candidates = board.pieces[turn][type];
            while (candidates) {
                const int from = pop(candidates);
                if (!(attacks_from(PieceType(type), turn, from, board.occupied) & bit(m.to()))) continue;
                const bool promotes = type == Pawn && (rank_of(m.to()) == 0 || rank_of(m.to()) == 7);
                const auto after = promotes ? Queen : PieceType(type);
                ExchangeBoard trial = board;
                trial.capture(turn, PieceType(type), from, m.to(), on_target, after);
                if (trial.attacked(trial.kings[turn], opposite(turn))) continue;
                ++depth;
                gain[depth] = ExchangeValue[on_target] + ExchangeValue[after] - ExchangeValue[type] - gain[depth - 1];
                chosen = trial; next_target = after; found = true; break;
            }
        }
        if (!found) break;
        board = chosen; on_target = next_target; turn = opposite(turn);
    }
    while (depth > 0) { gain[depth - 1] = -std::max(-gain[depth - 1], gain[depth]); --depth; }
    return gain[0];
}
} // namespace orient
