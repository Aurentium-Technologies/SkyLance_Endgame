#include "orient/chess.hpp"

#include <algorithm>
#include <bit>
#include <cassert>
#include <charconv>
#include <limits>
#include <sstream>

namespace orient {
namespace {
constexpr std::array<int, 8> Dx{0, 0, 1, -1, 1, -1, 1, -1};
constexpr std::array<int, 8> Dy{1, -1, 0, 0, 1, 1, -1, -1};
constexpr bool on_board(int x, int y) { return x >= 0 && x < 8 && y >= 0 && y < 8; }

struct AttackTables {
    std::array<Bitboard, 64> knight{}, king{};
    std::array<std::array<Bitboard, 64>, 2> pawn{};
    std::array<std::array<Bitboard, 8>, 64> ray{};
    constexpr AttackTables() {
        constexpr int nx[]{1, 2, 2, 1, -1, -2, -2, -1};
        constexpr int ny[]{2, 1, -1, -2, -2, -1, 1, 2};
        for (int s = 0; s < 64; ++s) {
            const int x = file_of(s), y = rank_of(s);
            for (int d = 0; d < 8; ++d) {
                if (on_board(x + nx[d], y + ny[d])) knight[s] |= bit((y + ny[d]) * 8 + x + nx[d]);
                if (on_board(x + Dx[d], y + Dy[d])) king[s] |= bit((y + Dy[d]) * 8 + x + Dx[d]);
                for (int xx = x + Dx[d], yy = y + Dy[d]; on_board(xx, yy); xx += Dx[d], yy += Dy[d])
                    ray[s][d] |= bit(yy * 8 + xx);
            }
            for (int c = 0; c < 2; ++c) {
                const int yy = y + (c == White ? 1 : -1);
                for (int xx : {x - 1, x + 1})
                    if (on_board(xx, yy)) pawn[c][s] |= bit(yy * 8 + xx);
            }
        }
    }
};
constexpr AttackTables Attacks{};

struct HashTables {
    std::array<std::array<std::array<std::uint64_t, 64>, 7>, 2> p{};
    std::array<std::uint64_t, 16> castling{};
    std::array<std::uint64_t, 8> ep{};
    std::uint64_t side{};
    constexpr HashTables() {
        std::uint64_t state = 0x6f7269656e745f31ULL;
        auto next = [&state]() constexpr {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            return state;
        };
        for (auto& color : p) for (auto& type : color) for (auto& square : type) square = next();
        for (auto& v : castling) v = next();
        for (auto& v : ep) v = next();
        side = next();
    }
};
constexpr HashTables Hash{};

Bitboard slider(int sq, Bitboard occupied, int first, int last) {
    if (sq < 0 || sq >= 64) return 0;
    Bitboard result = 0;
    for (int d = first; d < last; ++d) {
        Bitboard ray = Attacks.ray[sq][d];
        const Bitboard blockers = ray & occupied;
        if (blockers) {
            const bool increasing = Dy[d] * 8 + Dx[d] > 0;
            const int blocker = increasing ? std::countr_zero(blockers) : 63 - std::countl_zero(blockers);
            ray ^= Attacks.ray[blocker][d];
        }
        result |= ray;
    }
    return result;
}

int take_square(Bitboard& b) {
    const int sq = std::countr_zero(b);
    b &= b - 1;
    return sq;
}

char piece_character(int p) {
    constexpr char names[] = ".PNBRQK";
    const char ch = names[int(type_of(p))];
    return p < 0 ? char(ch + ('a' - 'A')) : ch;
}

int piece_from_character(char c) {
    const bool black = c >= 'a' && c <= 'z';
    const char upper = black ? char(c - ('a' - 'A')) : c;
    constexpr std::string_view names = "PNBRQK";
    const auto index = names.find(upper);
    return index == std::string_view::npos ? 0 : piece(black ? Black : White, PieceType(index + 1));
}

bool parse_integer(std::string_view s, int minimum, int& out) {
    if (s.empty()) return false;
    int value = 0;
    const auto result = std::from_chars(s.data(), s.data() + s.size(), value);
    if (result.ec != std::errc{} || result.ptr != s.data() + s.size() || value < minimum) return false;
    out = value;
    return true;
}

void save_undo(const Position& p, Undo& u) {
    u = Undo{};
    u.castling = p.castling; u.ep = p.ep;
    u.halfmove = p.halfmove; u.fullmove = p.fullmove;
    u.key = p.key; u.history_size = p.history.size();
}

int increment(int value) { return value < std::numeric_limits<int>::max() ? value + 1 : value; }
} // namespace

Bitboard knight_attacks(int sq) { return sq >= 0 && sq < 64 ? Attacks.knight[sq] : 0; }
Bitboard king_attacks(int sq) { return sq >= 0 && sq < 64 ? Attacks.king[sq] : 0; }
Bitboard pawn_attacks(Color c, int sq) { return sq >= 0 && sq < 64 ? Attacks.pawn[c][sq] : 0; }
Bitboard bishop_attacks(int sq, Bitboard occupied) { return slider(sq, occupied, 4, 8); }
Bitboard rook_attacks(int sq, Bitboard occupied) { return slider(sq, occupied, 0, 4); }
Bitboard attacks_from(PieceType pt, Color c, int sq, Bitboard occupied) {
    switch (pt) {
    case Pawn: return pawn_attacks(c, sq);
    case Knight: return knight_attacks(sq);
    case Bishop: return bishop_attacks(sq, occupied);
    case Rook: return rook_attacks(sq, occupied);
    case Queen: return bishop_attacks(sq, occupied) | rook_attacks(sq, occupied);
    case King: return king_attacks(sq);
    default: return 0;
    }
}

std::string Move::uci() const {
    if (!value) return "0000";
    std::string result;
    result += char('a' + file_of(from())); result += char('1' + rank_of(from()));
    result += char('a' + file_of(to())); result += char('1' + rank_of(to()));
    if (promotion() != Empty) {
        constexpr char promotions[] = ".pnbrqk";
        result += promotions[int(promotion())];
    }
    return result;
}

Position::Position() {
    history.reserve(1024);
    const bool ok = set_fen(StartFen);
    assert(ok);
    (void)ok;
}

void Position::put(int square, int p) {
    assert(square >= 0 && square < 64 && p && !board[square]);
    board[square] = std::int8_t(p);
    const auto c = color_of(p); const auto pt = type_of(p);
    bb[c][pt] |= bit(square); occupied[c] |= bit(square);
    key ^= Hash.p[c][pt][square];
}

void Position::remove(int square) {
    const int p = board[square];
    assert(p);
    const auto c = color_of(p); const auto pt = type_of(p);
    bb[c][pt] &= ~bit(square); occupied[c] &= ~bit(square);
    key ^= Hash.p[c][pt][square];
    board[square] = 0;
}

bool Position::set_fen(std::string_view input, std::string* error) {
    auto fail = [error](const char* message) { if (error) *error = message; return false; };
    std::istringstream stream{std::string(input)};
    std::array<std::string, 6> field;
    for (auto& f : field) if (!(stream >> f)) return fail("FEN must contain six fields");
    std::string trailing;
    if (stream >> trailing) return fail("Unexpected trailing FEN field");
    std::array<std::int8_t, 64> parsed{};
    int rank = 7, file = 0;
    for (char ch : field[0]) {
        if (ch == '/') {
            if (file != 8 || rank == 0) return fail("Invalid FEN rank separator");
            --rank; file = 0;
        } else if (ch >= '1' && ch <= '8') {
            file += ch - '0';
            if (file > 8) return fail("FEN rank exceeds eight squares");
        } else {
            const int p = piece_from_character(ch);
            if (!p || file >= 8) return fail("Invalid FEN piece placement");
            parsed[rank * 8 + file++] = std::int8_t(p);
        }
    }
    if (rank != 0 || file != 8) return fail("FEN must describe eight complete ranks");
    if (field[1] != "w" && field[1] != "b") return fail("Invalid side to move");
    const Color next_side = field[1] == "w" ? White : Black;
    int next_castling = 0;
    if (field[2] != "-") {
        for (char ch : field[2]) {
            int flag = ch == 'K' ? 1 : ch == 'Q' ? 2 : ch == 'k' ? 4 : ch == 'q' ? 8 : 0;
            if (!flag || (next_castling & flag)) return fail("Invalid castling rights");
            next_castling |= flag;
        }
    }
    int next_ep = -1;
    if (field[3] != "-") {
        if (field[3].size() != 2 || field[3][0] < 'a' || field[3][0] > 'h'
            || field[3][1] != (next_side == White ? '6' : '3')) return fail("Invalid en-passant target");
        next_ep = (field[3][1] - '1') * 8 + field[3][0] - 'a';
        const int captured = next_ep + (next_side == White ? -8 : 8);
        const int origin = next_ep + (next_side == White ? 8 : -8);
        if (parsed[next_ep] || parsed[captured] != piece(opposite(next_side), Pawn) || parsed[origin])
            return fail("En-passant target does not describe a double pawn push");
    }
    int next_halfmove = 0, next_fullmove = 1;
    if (!parse_integer(field[4], 0, next_halfmove) || !parse_integer(field[5], 1, next_fullmove))
        return fail("Invalid FEN move counters");

    std::array<int, 2> king_count{}, pawn_count{}, piece_count{};
    for (int sq = 0; sq < 64; ++sq) if (parsed[sq]) {
        const auto c = color_of(parsed[sq]); const auto pt = type_of(parsed[sq]);
        ++piece_count[c];
        if (pt == King) ++king_count[c];
        if (pt == Pawn) {
            ++pawn_count[c];
            if (rank_of(sq) == 0 || rank_of(sq) == 7) return fail("Pawn on promotion rank");
        }
    }
    for (Color c : {White, Black}) {
        if (king_count[c] != 1) return fail("FEN requires one king of each color");
        if (pawn_count[c] > 8 || piece_count[c] > 16) return fail("Too many pieces in FEN");
    }
    if (((next_castling & 1) && (parsed[4] != King || parsed[7] != Rook))
        || ((next_castling & 2) && (parsed[4] != King || parsed[0] != Rook))
        || ((next_castling & 4) && (parsed[60] != -King || parsed[63] != -Rook))
        || ((next_castling & 8) && (parsed[60] != -King || parsed[56] != -Rook)))
        return fail("Castling rights require kings and rooks on their starting squares");

    // Copy rather than construct: the default constructor itself loads StartFen.
    Position candidate = *this;
    candidate.board = parsed; candidate.bb = {}; candidate.occupied = {};
    candidate.side = next_side; candidate.castling = next_castling; candidate.ep = next_ep;
    candidate.halfmove = next_halfmove; candidate.fullmove = next_fullmove;
    for (int sq = 0; sq < 64; ++sq) if (parsed[sq]) {
        const int p = parsed[sq];
        candidate.bb[color_of(p)][type_of(p)] |= bit(sq);
        candidate.occupied[color_of(p)] |= bit(sq);
    }
    if (king_attacks(candidate.king_square(White)) & candidate.bb[Black][King])
        return fail("Kings may not be adjacent");
    if (candidate.attacked(candidate.king_square(opposite(next_side)), next_side))
        return fail("The side that just moved may not remain in check");
    candidate.key = candidate.recompute_key();
    candidate.history.clear(); candidate.history.reserve(1024); candidate.history.push_back(candidate.key);
    *this = std::move(candidate);
    if (error) error->clear();
    return true;
}

std::string Position::fen() const {
    std::string result;
    for (int rank = 7; rank >= 0; --rank) {
        int empty = 0;
        for (int file = 0; file < 8; ++file) {
            const int p = board[rank * 8 + file];
            if (!p) ++empty;
            else {
                if (empty) { result += char('0' + empty); empty = 0; }
                result += piece_character(p);
            }
        }
        if (empty) result += char('0' + empty);
        if (rank) result += '/';
    }
    result += side == White ? " w " : " b ";
    if (!castling) result += '-';
    else {
        if (castling & 1) result += 'K';
        if (castling & 2) result += 'Q';
        if (castling & 4) result += 'k';
        if (castling & 8) result += 'q';
    }
    result += ' ';
    if (ep < 0) result += '-';
    else { result += char('a' + file_of(ep)); result += char('1' + rank_of(ep)); }
    result += ' '; result += std::to_string(halfmove);
    result += ' '; result += std::to_string(fullmove);
    return result;
}

int Position::king_square(Color c) const { return bb[c][King] ? std::countr_zero(bb[c][King]) : -1; }

bool Position::attacked(int square, Color by) const {
    if (square < 0 || square >= 64) return false;
    return (pawn_attacks(opposite(by), square) & bb[by][Pawn])
        || (knight_attacks(square) & bb[by][Knight])
        || (king_attacks(square) & bb[by][King])
        || (bishop_attacks(square, occupancy()) & (bb[by][Bishop] | bb[by][Queen]))
        || (rook_attacks(square, occupancy()) & (bb[by][Rook] | bb[by][Queen]));
}

bool Position::in_check() const { return attacked(king_square(side), opposite(side)); }

MoveList Position::pseudo_moves(bool tactical_only) const {
    MoveList result;
    const Bitboard all = occupancy(), enemy = occupied[opposite(side)] & ~bb[opposite(side)][King];
    Bitboard pawns = bb[side][Pawn];
    const int delta = side == White ? 8 : -8;
    auto add_pawn = [&result](int from, int to, std::uint32_t flags) {
        if (rank_of(to) == 0 || rank_of(to) == 7)
            for (PieceType pt : {Queen, Rook, Bishop, Knight}) result.push(Move(from, to, pt, flags));
        else result.push(Move(from, to, Empty, flags));
    };
    while (pawns) {
        const int from = take_square(pawns), to = from + delta;
        if (to >= 0 && to < 64 && !board[to]) {
            if (!tactical_only || rank_of(to) == 0 || rank_of(to) == 7) add_pawn(from, to, 0);
            if (!tactical_only && rank_of(from) == (side == White ? 1 : 6) && !board[to + delta])
                result.push(Move(from, to + delta, Empty, Move::DoublePush));
        }
        Bitboard captures = pawn_attacks(side, from) & enemy;
        while (captures) add_pawn(from, take_square(captures), Move::Capture);
        if (ep >= 0 && (pawn_attacks(side, from) & bit(ep)) && !board[ep]
            && board[ep - delta] == piece(opposite(side), Pawn))
            result.push(Move(from, ep, Empty, Move::Capture | Move::EnPassant));
    }
    for (PieceType pt : {Knight, Bishop, Rook, Queen, King}) {
        Bitboard pieces = bb[side][pt];
        while (pieces) {
            const int from = take_square(pieces);
            Bitboard targets = attacks_from(pt, side, from, all) & ~occupied[side] & ~bb[opposite(side)][King];
            if (tactical_only) targets &= enemy;
            while (targets) {
                const int to = take_square(targets);
                result.push(Move(from, to, Empty, board[to] ? std::uint32_t(Move::Capture) : 0u));
            }
        }
    }
    if (!tactical_only) {
        const Color them = opposite(side);
        const int home = side == White ? 4 : 60;
        const int right = side == White ? 1 : 4;
        if (board[home] == piece(side, King) && !attacked(home, them)) {
            if ((castling & right) && board[home + 3] == piece(side, Rook)
                && !board[home + 1] && !board[home + 2]
                && !attacked(home + 1, them) && !attacked(home + 2, them))
                result.push(Move(home, home + 2, Empty, Move::Castle));
            if ((castling & (right * 2)) && board[home - 4] == piece(side, Rook)
                && !board[home - 1] && !board[home - 2] && !board[home - 3]
                && !attacked(home - 1, them) && !attacked(home - 2, them))
                result.push(Move(home, home - 2, Empty, Move::Castle));
        }
    }
    assert(result.count <= 256);
    return result;
}

MoveList Position::legal_moves(bool tactical_only) {
    const Color us = side;
    const auto candidates = pseudo_moves(tactical_only);
    MoveList legal;
    for (Move m : candidates) {
        Undo undo;
        make(m, undo);
        const bool valid = !attacked(king_square(us), side);
        unmake(m, undo);
        if (valid) legal.push(m);
    }
    return legal;
}

bool Position::has_legal_move() {
    const Color us = side;
    for (Move move : pseudo_moves()) {
        Undo undo;
        make(move, undo);
        const bool legal = !attacked(king_square(us), side);
        unmake(move, undo);
        if (legal) return true;
    }
    return false;
}

bool Position::king_safe_after(Move move) const {
    const Color them = opposite(side);
    const bool king_move = type_of(board[move.from()]) == King;
    const int king = king_move ? move.to() : king_square(side);
    assert(king >= 0);
    const int capture_square = move.has(Move::EnPassant)
        ? move.to() + (side == White ? -8 : 8) : move.to();
    const Bitboard captured = move.capture() ? bit(capture_square) : 0;
    Bitboard after = (occupancy() & ~bit(move.from()) & ~captured) | bit(move.to());
    if (move.has(Move::Castle)) {
        const int rook_from = move.to() > move.from() ? move.from() + 3 : move.from() - 4;
        const int rook_to = move.to() > move.from() ? move.from() + 1 : move.from() - 1;
        after = (after & ~bit(rook_from)) | bit(rook_to);
    }
    // The captured enemy is removed from both occupancy and attack-source sets.
    // Pseudo generation already checked castling's initial/transit squares.
    return !((pawn_attacks(side, king) & bb[them][Pawn] & ~captured)
        || (knight_attacks(king) & bb[them][Knight] & ~captured)
        || (king_attacks(king) & bb[them][King])
        || (bishop_attacks(king, after) & (bb[them][Bishop] | bb[them][Queen]) & ~captured)
        || (rook_attacks(king, after) & (bb[them][Rook] | bb[them][Queen]) & ~captured));
}

MoveList Position::legal_moves_direct(bool tactical_only) const {
    MoveList legal;
    for (Move move : pseudo_moves(tactical_only))
        if (king_safe_after(move)) legal.push(move);
    return legal;
}

bool Position::has_legal_move_direct() const {
    for (Move move : pseudo_moves()) if (king_safe_after(move)) return true;
    return false;
}

Move Position::parse_uci(std::string_view text) {
    if (text.size() != 4 && text.size() != 5) return Move{};
    if (text[0] < 'a' || text[0] > 'h' || text[2] < 'a' || text[2] > 'h'
        || text[1] < '1' || text[1] > '8' || text[3] < '1' || text[3] > '8') return Move{};
    const int from = (text[1] - '1') * 8 + text[0] - 'a';
    const int to = (text[3] - '1') * 8 + text[2] - 'a';
    PieceType promotion = Empty;
    if (text.size() == 5) {
        if (text[4] == 'q') promotion = Queen;
        else if (text[4] == 'r') promotion = Rook;
        else if (text[4] == 'b') promotion = Bishop;
        else if (text[4] == 'n') promotion = Knight;
        else return Move{};
    }
    for (Move move : legal_moves())
        if (move.from() == from && move.to() == to && move.promotion() == promotion) return move;
    return Move{};
}

int Position::ep_hash_file() const {
    if (ep < 0 || ep >= 64 || board[ep]) return -1;
    const Color them = opposite(side);
    const int captured = ep + (side == White ? -8 : 8);
    if (captured < 0 || captured >= 64 || board[captured] != piece(them, Pawn)) return -1;
    Bitboard candidates = pawn_attacks(them, ep) & bb[side][Pawn];
    const int king = king_square(side);
    if (king < 0) return -1;
    while (candidates) {
        const int from = take_square(candidates);
        const Bitboard hypothetical = (occupancy() & ~bit(from) & ~bit(captured)) | bit(ep);
        const bool check = (pawn_attacks(side, king) & (bb[them][Pawn] & ~bit(captured)))
            || (knight_attacks(king) & bb[them][Knight])
            || (king_attacks(king) & bb[them][King])
            || (bishop_attacks(king, hypothetical) & (bb[them][Bishop] | bb[them][Queen]))
            || (rook_attacks(king, hypothetical) & (bb[them][Rook] | bb[them][Queen]));
        if (!check) return file_of(ep);
    }
    return -1;
}

void Position::make(Move m, Undo& undo) {
    save_undo(*this, undo);
    const int from = m.from(), to = m.to(), moving = board[from];
    assert(moving && color_of(moving) == side && type_of(board[to]) != King);
    const auto pt = type_of(moving);
    undo.capture_square = m.has(Move::EnPassant) ? to + (side == White ? -8 : 8) : to;
    undo.captured = board[undo.capture_square];
    const int old_ep_file = ep_hash_file();
    if (old_ep_file >= 0) key ^= Hash.ep[old_ep_file];
    key ^= Hash.castling[castling];
    ep = -1;
    remove(from);
    if (undo.captured) remove(undo.capture_square);
    put(to, m.promotion() == Empty ? moving : piece(side, m.promotion()));
    if (m.has(Move::Castle)) {
        const int rook_from = to > from ? from + 3 : from - 4;
        const int rook_to = to > from ? from + 1 : from - 1;
        remove(rook_from); put(rook_to, piece(side, Rook));
    }
    if (pt == King) castling &= side == White ? ~3 : ~12;
    for (int square : {from, to}) {
        if (square == 0) castling &= ~2;
        if (square == 7) castling &= ~1;
        if (square == 56) castling &= ~8;
        if (square == 63) castling &= ~4;
    }
    if (pt == Pawn && (to - from == 16 || from - to == 16)) ep = (from + to) / 2;
    halfmove = pt == Pawn || undo.captured ? 0 : increment(halfmove);
    if (side == Black) fullmove = increment(fullmove);
    side = opposite(side); key ^= Hash.side;
    key ^= Hash.castling[castling];
    const int new_ep_file = ep_hash_file();
    if (new_ep_file >= 0) key ^= Hash.ep[new_ep_file];
    history.push_back(key);
}

void Position::unmake(Move m, const Undo& undo) {
    side = opposite(side);
    const int from = m.from(), to = m.to();
    const int moving = m.promotion() == Empty ? board[to] : piece(side, Pawn);
    remove(to); put(from, moving);
    if (m.has(Move::Castle)) {
        const int rook_from = to > from ? from + 3 : from - 4;
        const int rook_to = to > from ? from + 1 : from - 1;
        remove(rook_to); put(rook_from, piece(side, Rook));
    }
    if (undo.captured) put(undo.capture_square, undo.captured);
    castling = undo.castling; ep = undo.ep;
    halfmove = undo.halfmove; fullmove = undo.fullmove;
    key = undo.key;
    history.resize(undo.history_size);
}

void Position::make_null(Undo& undo) {
    save_undo(*this, undo);
    const int old_ep_file = ep_hash_file();
    if (old_ep_file >= 0) key ^= Hash.ep[old_ep_file];
    ep = -1;
    halfmove = increment(halfmove);
    if (side == Black) fullmove = increment(fullmove);
    side = opposite(side); key ^= Hash.side;
}

void Position::unmake_null(const Undo& undo) {
    side = opposite(side);
    castling = undo.castling; ep = undo.ep;
    halfmove = undo.halfmove; fullmove = undo.fullmove;
    key = undo.key; history.resize(undo.history_size);
}

int Position::repetition_count() const {
    int count = 0;
    const auto limit = std::min(history.size(), std::size_t(halfmove) + 1);
    for (std::size_t n = 0; n < limit; ++n)
        if (history[history.size() - n - 1] == key) ++count;
    return count;
}

bool Position::insufficient_material() const {
    if (bb[White][Pawn] || bb[Black][Pawn] || bb[White][Rook] || bb[Black][Rook]
        || bb[White][Queen] || bb[Black][Queen]) return false;
    const Bitboard bishops = bb[White][Bishop] | bb[Black][Bishop];
    const Bitboard knights = bb[White][Knight] | bb[Black][Knight];
    if (std::popcount(bishops | knights) <= 1) return true;
    if (knights) return false;
    constexpr Bitboard dark = 0xaa55aa55aa55aa55ULL;
    return !(bishops & dark) || !(bishops & ~dark);
}

std::uint64_t Position::recompute_key() const {
    std::uint64_t result = Hash.castling[castling];
    if (side == Black) result ^= Hash.side;
    for (int sq = 0; sq < 64; ++sq) if (board[sq])
        result ^= Hash.p[color_of(board[sq])][type_of(board[sq])][sq];
    const int ep_file = ep_hash_file();
    if (ep_file >= 0) result ^= Hash.ep[ep_file];
    return result;
}

bool Position::consistent() const {
    std::array<std::array<Bitboard, 7>, 2> expected{};
    std::array<Bitboard, 2> occ{};
    for (int sq = 0; sq < 64; ++sq) if (board[sq]) {
        if (board[sq] < -King || board[sq] > King) return false;
        const auto c = color_of(board[sq]); const auto pt = type_of(board[sq]);
        expected[c][pt] |= bit(sq); occ[c] |= bit(sq);
    }
    return expected == bb && occ == occupied && !(occupied[White] & occupied[Black])
        && std::popcount(bb[White][King]) == 1 && std::popcount(bb[Black][King]) == 1
        && castling >= 0 && castling <= 15 && ep >= -1 && ep < 64
        && halfmove >= 0 && fullmove >= 1 && recompute_key() == key;
}

std::uint64_t perft(Position& p, int depth) {
    if (depth <= 0) return 1;
    std::uint64_t count = 0;
    const Color us = p.side;
    for (Move m : p.pseudo_moves()) {
        Undo undo;
        p.make(m, undo);
        if (!p.attacked(p.king_square(us), p.side)) count += depth == 1 ? 1 : perft(p, depth - 1);
        p.unmake(m, undo);
    }
    return count;
}
} // namespace orient
