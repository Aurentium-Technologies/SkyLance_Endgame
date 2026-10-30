#include "orient/chess.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace orient;
std::uint64_t checks = 0;
void check(bool condition, std::string_view message) {
    ++checks;
    if (!condition) throw std::runtime_error(std::string(message));
}
void same(const Position& a, const Position& b, std::string_view message) {
    check(a.board == b.board && a.bb == b.bb && a.occupied == b.occupied
        && a.side == b.side && a.castling == b.castling && a.ep == b.ep
        && a.halfmove == b.halfmove && a.fullmove == b.fullmove && a.key == b.key
        && a.history == b.history, message);
}
Position position(std::string_view fen) {
    Position p;
    std::string error;
    check(p.set_fen(fen, &error), "fixture FEN rejected: " + std::string(fen) + ": " + error);
    check(p.consistent(), "fixture position inconsistent");
    return p;
}
void play(Position& p, std::string_view text) {
    const Move move = p.parse_uci(text);
    check(bool(move), "expected legal move: " + std::string(text));
    Undo undo;
    p.make(move, undo);
    check(p.consistent(), "position inconsistent after move");
}
Bitboard reference_slider(int sq, Bitboard occupied, bool diagonal) {
    Bitboard result = 0;
    for (int dx = -1; dx <= 1; ++dx) for (int dy = -1; dy <= 1; ++dy) {
        if ((!dx && !dy) || (diagonal ? (!dx || !dy) : (dx && dy))) continue;
        for (int x = file_of(sq) + dx, y = rank_of(sq) + dy;
             x >= 0 && x < 8 && y >= 0 && y < 8; x += dx, y += dy) {
            const Bitboard target = bit(y * 8 + x);
            result |= target;
            if (occupied & target) break;
        }
    }
    return result;
}
void attack_tests() {
    std::mt19937_64 random(0x4f5249454e545241ULL);
    for (int sq = 0; sq < 64; ++sq) {
        for (int trial = 0; trial < 1000; ++trial) {
            const auto occupied = random();
            check(bishop_attacks(sq, occupied) == reference_slider(sq, occupied, true), "bishop ray mismatch");
            check(rook_attacks(sq, occupied) == reference_slider(sq, occupied, false), "rook ray mismatch");
        }
        Bitboard knight = 0, king = 0;
        for (int target = 0; target < 64; ++target) {
            const int dx = std::abs(file_of(sq) - file_of(target));
            const int dy = std::abs(rank_of(sq) - rank_of(target));
            if ((dx == 1 && dy == 2) || (dx == 2 && dy == 1)) knight |= bit(target);
            if (dx <= 1 && dy <= 1 && (dx || dy)) king |= bit(target);
        }
        check(knight_attacks(sq) == knight && king_attacks(sq) == king, "leaper attack mismatch");
        for (Color color : {White, Black}) {
            Bitboard expected = 0;
            for (int target = 0; target < 64; ++target)
                if (std::abs(file_of(sq) - file_of(target)) == 1
                    && rank_of(target) - rank_of(sq) == (color == White ? 1 : -1)) expected |= bit(target);
            check(pawn_attacks(color, sq) == expected, "pawn attack mismatch");
        }
    }
}
void fen_tests() {
    Position p;
    check(p.fen() == StartFen, "initial FEN round trip");
    play(p, "e2e4");
    play(p, "e7e5");
    const Position saved = p;
    const std::array<std::string_view, 23> invalid{
        "", "8/8/8/8/8/8/8/8 w - - 0 1", "8/8/8/8/8/8/8/K6k w - - 0",
        "8/8/8/8/8/8/8/K6k w - - 0 1 trailing", "8/8/8/8/8/8/8/K6k x - - 0 1",
        "8/8/8/8/8/8/8/K6k w KK - 0 1", "8/8/8/8/8/8/8/K6k w K - 0 1",
        "8/8/8/8/8/8/8/K6k w - - -1 1", "8/8/8/8/8/8/8/K6k w - - 0 0",
        "8/8/8/8/8/8/8/K6k w - - 0 2147483648", "8/8/8/8/8/8/8/K6k w - - 0x1 1",
        "8/8/8/8/8/8/8/K6k w - a3 0 1", "8/8/8/8/8/8/8/K6k w - a6 0 1",
        "8/8/8/8/8/8/8/K6k w - i6 0 1", "8/8/8/8/8/8/8/K6k w - aa6 0 1",
        "8/8/8/8/8/8/8/K5kk w - - 0 1", "8/8/8/8/8/8/8/Kk6 w - - 0 1",
        "8/8/8/8/8/8/8/K5Rk w - - 0 1", "P7/8/8/8/8/8/8/K6k w - - 0 1",
        "8/8/8/8/8/8/8/K5pk w - - 0 1", "8/8/8/8/8/8/8/K7k w - - 0 1",
        "8/8/8/8/8/8/8/9 w - - 0 1", "8/8/8/8/8/8/8/K5Zk w - - 0 1"};
    for (auto fen : invalid) {
        std::string error;
        check(!p.set_fen(fen, &error), "invalid FEN accepted: " + std::string(fen));
        check(!error.empty(), "missing FEN error");
        same(p, saved, "rejected FEN mutated position/history");
    }
    check(p.set_fen("7k/8/8/8/8/8/8/K7 b - - 2147483647 2147483647"), "maximum counters rejected");
    play(p, "h8g8");
    check(p.halfmove == 2147483647 && p.fullmove == 2147483647, "counter overflow");
    for (auto text : {"", "e2e4q", "e2e5", "e2e4x", "e9e4", "i2e4", "e2e4extra", "0000"})
        check(!Position{}.parse_uci(text), "malformed/illegal UCI move accepted");
}
void special_tests() {
    auto p = position("7k/P7/8/8/8/8/8/7K w - - 0 1");
    int promotions = 0;
    for (Move move : p.legal_moves()) if (move.from() == 48) {
        ++promotions;
        check(move.promotion() != Empty && move.uci().size() == 5, "missing promotion choice");
        const Position saved = p;
        Undo undo;
        p.make(move, undo);
        check(p.board[56] == piece(White, move.promotion()) && !p.board[48] && p.halfmove == 0, "promotion state");
        check(p.consistent(), "promotion hash/bitboards");
        p.unmake(move, undo);
        same(p, saved, "promotion unmake");
    }
    check(promotions == 4 && !p.parse_uci("a7a8"), "all four promotions required");
    p = position("1r5k/P7/8/8/8/8/8/7K w - - 0 1");
    for (auto suffix : {"q", "r", "b", "n"}) {
        const auto move = p.parse_uci("a7b8" + std::string(suffix));
        check(move && move.capture(), "capture underpromotion missing");
        const Position saved = p;
        Undo undo; p.make(move, undo); p.unmake(move, undo);
        same(p, saved, "capture promotion unmake");
    }
    p = position("k7/8/8/r4pPK/8/8/8/8 w - f6 0 1");
    check(!p.parse_uci("g5f6"), "discovered-check en passant accepted");
    const auto without_illegal_ep = position("k7/8/8/r4pPK/8/8/8/8 w - - 0 1");
    check(p.key == without_illegal_ep.key, "illegal EP changes repetition hash");
    p = position("7k/8/8/5pP1/8/8/8/7K w - f6 0 1");
    const auto without_legal_ep = position("7k/8/8/5pP1/8/8/8/7K w - - 0 1");
    check(p.key != without_legal_ep.key, "legal EP omitted from hash");
    const Position ep_saved = p;
    const auto ep_move = p.parse_uci("g5f6");
    check(ep_move && ep_move.has(Move::EnPassant), "legal EP missing");
    Undo ep_undo; p.make(ep_move, ep_undo);
    check(p.board[45] == Pawn && !p.board[37] && !p.board[38] && p.consistent(), "EP state/hash");
    p.unmake(ep_move, ep_undo); same(p, ep_saved, "EP unmake");
    p = position("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1");
    for (auto text : {"e1g1", "e1c1"}) {
        const Position saved = p;
        const auto move = p.parse_uci(text);
        check(move && move.has(Move::Castle), "castling missing");
        Undo undo; p.make(move, undo);
        check(!(p.castling & 3) && p.consistent(), "castling rights/hash");
        p.unmake(move, undo); same(p, saved, "castling unmake");
    }
    play(p, "h1h8");
    check(p.castling == 10, "moving/captured rook failed to clear rights");
    p = position("r3k2r/8/8/8/8/5r2/8/R3K2R w KQkq - 0 1");
    check(!p.parse_uci("e1g1") && p.parse_uci("e1c1"), "castling through attacked path");
    p = position("r3k2r/8/8/8/8/8/8/R3KB1R w KQkq - 0 1");
    check(!p.parse_uci("e1g1"), "castling through occupied path");
    p = Position{};
    for (int repeat = 0; repeat < 2; ++repeat)
        for (auto move : {"g1f3", "g8f6", "f3g1", "f6g8"}) play(p, move);
    check(p.repetition_count() == 3, "threefold repetition missing");
    const Position null_saved = p;
    Undo null_undo; p.make_null(null_undo);
    check(p.history == null_saved.history && p.key == p.recompute_key(), "null move changed history/hash");
    p.unmake_null(null_undo); same(p, null_saved, "null unmake");
    for (auto fen : {"7k/8/8/8/8/8/8/K7 w - - 0 1", "7k/8/8/8/8/8/8/KB6 w - - 0 1",
                     "7k/8/8/8/8/8/8/KN6 w - - 0 1", "7k/8/8/8/8/8/4b3/KB6 w - - 0 1"})
        check(position(fen).insufficient_material(), "dead material not detected");
    for (auto fen : {"7k/8/8/8/8/8/8/KNN5 w - - 0 1", "7k/8/8/8/8/8/8/KBN5 w - - 0 1",
                     "7k/8/8/8/8/8/8/KBb5 w - - 0 1", "7k/8/8/8/8/8/P7/K7 w - - 0 1"})
        check(!position(fen).insufficient_material(), "live material declared dead");
}
void randomized_restoration() {
    std::mt19937_64 random(0x4f7269656e743230ULL);
    std::uint64_t plies = 0;
    while (plies < 100000) {
        Position p;
        std::vector<Position> saved;
        std::vector<Move> moves;
        std::vector<Undo> undos;
        const int length = 40 + int(random() % 161);
        for (int ply = 0; ply < length && plies < 100000; ++ply) {
            const auto legal = p.legal_moves();
            const auto direct = p.legal_moves_direct();
            check(legal.size() == direct.size() && std::equal(legal.begin(), legal.end(), direct.begin()),
                  "direct legality differs in randomized make/unmake walk");
            if (legal.empty()) break;
            const Move move = legal[int(random() % std::uint64_t(legal.size()))];
            saved.push_back(p); moves.push_back(move); undos.emplace_back();
            p.make(move, undos.back());
            check(p.consistent(), "random make inconsistent");
            check(p.history.back() == p.key && p.history.size() == saved.back().history.size() + 1, "random make history");
            ++plies;
        }
        while (!moves.empty()) {
            p.unmake(moves.back(), undos.back());
            same(p, saved.back(), "random unmake failed exact restoration");
            check(p.consistent(), "random unmake inconsistent");
            moves.pop_back(); undos.pop_back(); saved.pop_back();
        }
        same(p, Position{}, "random game failed to restore start position");
    }
    std::cout << "randomized make/unmake: " << plies << " plies PASS\n";
}

MoveList query_equivalence(Position& p) {
    const Position saved = p;
    const bool exists = p.has_legal_move();
    same(p, saved, "early-exit legal query failed exact restoration");
    const auto all = p.legal_moves();
    same(p, saved, "reference legal query failed exact restoration");
    check(exists == !all.empty(), "legal move existence differs from full reference");
    const auto tactical = p.legal_moves(true);
    same(p, saved, "tactical legal query failed exact restoration");
    int index = 0;
    for (Move move : all) if (move.capture() || move.promotion() != Empty) {
        check(index < tactical.size(), "tactical query omitted reference move");
        check(tactical[index++] == move, "tactical query changed filtered reference ordering");
    }
    check(index == tactical.size(), "tactical query added a quiet move");
    check(p.consistent(), "legal query left inconsistent hash or bitboards");
    const auto direct = p.legal_moves_direct();
    const auto direct_tactical = p.legal_moves_direct(true);
    check(all.size() == direct.size() && std::equal(all.begin(), all.end(), direct.begin()),
          "direct legal list/order differs from make/unmake reference");
    check(tactical.size() == direct_tactical.size()
          && std::equal(tactical.begin(), tactical.end(), direct_tactical.begin()),
          "direct tactical list/order differs from make/unmake reference");
    check(p.has_legal_move_direct() == exists, "direct existence query differs from reference");
    same(p, saved, "direct legality query mutated position state");
    return all;
}

void legal_query_tests() {
    struct Fixture { std::string_view fen; bool has_move; };
    for (const auto& fixture : std::array<Fixture, 18>{{
        {"7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", false}, // Checkmate.
        {"7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", false}, // Stalemate.
        {"8/8/8/8/8/6k1/6q1/7K w - - 0 1", false},
        {"4r1k1/8/8/8/8/8/8/4K3 w - - 0 1", true}, // Quiet check evasions.
        {"4r1k1/8/8/8/8/8/4N3/4K3 w - - 0 1", true}, // Pinned knight pseudo-moves precede king.
        {"r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", true},
        {"r3k2r/8/8/8/8/5r2/8/R3K2R w KQkq - 0 1", true},
        {"k7/8/8/r4pPK/8/8/8/8 w - f6 0 1", true}, // Illegal discovered-check EP.
        {"7k/8/8/5pP1/8/8/8/7K w - f6 0 1", true},
        {"1r5k/P7/8/8/8/8/8/7K w - - 0 1", true}, // Promotion and capture promotions.
        {"7k/8/8/8/8/8/p7/1R5K b - - 0 1", true},
        {"7k/8/8/8/8/8/8/K7 w - - 150 90", true}, // Existence is independent of drawn clocks/material.
        {"4k3/8/8/3pP3/4K3/8/8/8 w - d6 0 1", true}, // EP removes the checking pawn.
        {"3r3k/8/8/2pP4/8/8/8/3K4 w - c6 0 1", true}, // EP would open a vertical rook line.
        {"4r1k1/8/8/8/1b6/8/8/4K3 w - - 0 1", true}, // Double check.
        {"4r1k1/8/8/8/8/8/4b3/4K3 w - - 0 1", true}, // Capturing the blocker would expose a rook.
        {"7k/8/8/8/8/8/8/r3K3 w - - 0 1", true}, // King departure must uncover the rook ray.
        {StartFen, true}}}) {
        Position p = position(fixture.fen);
        const auto moves = query_equivalence(p);
        check(!moves.empty() == fixture.has_move, "targeted legal query fixture expectation");
    }
    std::mt19937_64 random(0x71756572795f7631ULL);
    Position p;
    constexpr int positions = 20000;
    for (int index = 0; index < positions; ++index) {
        const auto moves = query_equivalence(p);
        if (moves.empty() || index % 200 == 199) { p = Position{}; continue; }
        const Move move = moves[int(random() % std::uint64_t(moves.size()))];
        Undo undo;
        p.make(move, undo);
    }
    std::cout << "reference/direct legal existence/tactical ordering: 18 fixtures and " << positions << " random positions PASS\n";
}

std::uint64_t direct_perft(Position& p, int depth) {
    if (depth == 0) return 1;
    const auto moves = p.legal_moves_direct();
    if (depth == 1) return std::uint64_t(moves.size());
    std::uint64_t nodes = 0;
    for (Move move : moves) {
        Undo undo; p.make(move, undo);
        nodes += direct_perft(p, depth - 1);
        p.unmake(move, undo);
    }
    return nodes;
}

void perft_tests(bool extended, bool direct = false) {
    // Public correctness fixtures only, verified against:
    // https://chessprogramming.org/Perft_Results (2026-10-23).
    // No external engine implementation or evaluation is used by this test.
    struct Fixture { const char* name; std::string_view fen; int depth; std::uint64_t nodes; };
    const std::array<Fixture, 6> fixtures{{
        {"start", StartFen, extended ? 6 : 5, extended ? 119060324ULL : 4865609ULL},
        {"kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 4, 4085603},
        {"rook-pawn", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 5, 674624},
        {"promotions-castling", "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 4, 422333},
        {"promotion-tactics", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 4, 2103487},
        {"middlegame", "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10", 4, 3894594}}};
    for (const auto& fixture : fixtures) {
        Position p = position(fixture.fen);
        const Position saved = p;
        const auto nodes = direct ? direct_perft(p, fixture.depth) : perft(p, fixture.depth);
        std::cout << (direct ? "direct perft " : "perft ") << fixture.name << " depth " << fixture.depth << ": " << nodes << '\n';
        check(nodes == fixture.nodes, "canonical perft count mismatch: " + std::string(fixture.name));
        same(p, saved, "perft mutated state");
    }
    Position p;
    for (const auto& [depth, nodes] : std::array<std::pair<int, std::uint64_t>, 4>{{{1,20},{2,400},{3,8902},{4,197281}}})
        check((direct ? direct_perft(p, depth) : perft(p, depth)) == nodes, "early start-position perft mismatch");
}
}
int main(int argc, char** argv) {
    try {
        const bool extended = argc == 2 && std::string_view(argv[1]) == "--extended";
        const bool queries_only = argc == 2 && std::string_view(argv[1]) == "--queries-only";
        const bool extended_direct = argc == 2 && std::string_view(argv[1]) == "--extended-direct";
        check(argc == 1 || extended || queries_only || extended_direct,
              "usage: test_chess [--extended|--extended-direct|--queries-only]");
        legal_query_tests();
        if (!queries_only) {
            attack_tests(); fen_tests(); special_tests(); randomized_restoration();
            perft_tests(extended || extended_direct, extended_direct);
        }
        std::cout << "chess core: PASS (" << checks << " explicit checks)\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "chess core: FAIL after " << checks << " checks: " << error.what() << '\n';
        return 1;
    }
}
