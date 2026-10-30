#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace orient {
using Bitboard = std::uint64_t;
enum Color : int { White = 0, Black = 1 };
constexpr Color opposite(Color c) { return Color(int(c) ^ 1); }
enum PieceType : int { Empty = 0, Pawn, Knight, Bishop, Rook, Queen, King };
constexpr int piece(Color c, PieceType pt) { return c == White ? int(pt) : -int(pt); }
constexpr Color color_of(int p) { return p > 0 ? White : Black; }
constexpr PieceType type_of(int p) { return PieceType(p < 0 ? -p : p); }
constexpr Bitboard bit(int sq) { return Bitboard(1) << sq; }
constexpr int file_of(int sq) { return sq & 7; }
constexpr int rank_of(int sq) { return sq >> 3; }
inline constexpr std::string_view StartFen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

struct Move {
    std::uint32_t value = 0;
    enum Flag : std::uint32_t { Capture = 1u << 15, EnPassant = 1u << 16,
                              Castle = 1u << 17, DoublePush = 1u << 18 };
    constexpr Move() = default;
    constexpr explicit Move(std::uint32_t v) : value(v) {}
    constexpr Move(int from, int to, PieceType promotion = Empty, std::uint32_t flags = 0)
        : value(std::uint32_t(from) | (std::uint32_t(to) << 6)
                | (std::uint32_t(promotion) << 12) | flags) {}
    constexpr int from() const { return int(value & 63); }
    constexpr int to() const { return int((value >> 6) & 63); }
    constexpr PieceType promotion() const { return PieceType((value >> 12) & 7); }
    constexpr bool has(Flag f) const { return (value & f) != 0; }
    constexpr bool capture() const { return has(Capture); }
    constexpr explicit operator bool() const { return value != 0; }
    constexpr bool operator==(const Move&) const = default;
    std::string uci() const;
};

struct MoveList {
    std::array<Move, 256> moves{};
    int count = 0;
    void push(Move m) { moves[std::size_t(count++)] = m; }
    bool empty() const { return count == 0; }
    int size() const { return count; }
    Move* begin() { return moves.data(); }
    Move* end() { return moves.data() + count; }
    const Move* begin() const { return moves.data(); }
    const Move* end() const { return moves.data() + count; }
    Move& operator[](int i) { return moves[std::size_t(i)]; }
    const Move& operator[](int i) const { return moves[std::size_t(i)]; }
};

struct Undo {
    int captured = 0, capture_square = -1, castling = 0, ep = -1;
    int halfmove = 0, fullmove = 1;
    std::uint64_t key = 0;
    std::size_t history_size = 0;
};

Bitboard knight_attacks(int sq);
Bitboard king_attacks(int sq);
Bitboard pawn_attacks(Color c, int sq);
Bitboard bishop_attacks(int sq, Bitboard occupied);
Bitboard rook_attacks(int sq, Bitboard occupied);
Bitboard attacks_from(PieceType pt, Color c, int sq, Bitboard occupied);

class Position {
public:
    std::array<std::int8_t, 64> board{};
    std::array<std::array<Bitboard, 7>, 2> bb{};
    std::array<Bitboard, 2> occupied{};
    Color side = White;
    int castling = 0, ep = -1, halfmove = 0, fullmove = 1;
    std::uint64_t key = 0;
    std::vector<std::uint64_t> history;

    Position();
    bool set_fen(std::string_view fen, std::string* error = nullptr);
    std::string fen() const;
    Bitboard occupancy() const { return occupied[White] | occupied[Black]; }
    int king_square(Color c) const;
    bool attacked(int square, Color by) const;
    bool in_check() const;
    MoveList pseudo_moves(bool tactical_only = false) const;
    MoveList legal_moves(bool tactical_only = false);
    // Existence query; restores every position field before returning.
    bool has_legal_move();
    // Const reference-equivalent queries using hypothetical occupancy only.
    MoveList legal_moves_direct(bool tactical_only = false) const;
    bool has_legal_move_direct() const;
    Move parse_uci(std::string_view text);
    void make(Move move, Undo& undo);
    void unmake(Move move, const Undo& undo);
    void make_null(Undo& undo);
    void unmake_null(const Undo& undo);
    int repetition_count() const;
    bool insufficient_material() const;
    std::uint64_t recompute_key() const;
    bool consistent() const;
private:
    void put(int square, int p);
    void remove(int square);
    int ep_hash_file() const;
    bool king_safe_after(Move move) const;
};

std::uint64_t perft(Position& position, int depth);
} // namespace orient
