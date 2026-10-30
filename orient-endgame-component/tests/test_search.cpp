#include "orient/search.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace orient;

namespace {
int checks = 0;
void check(bool condition, const std::string& description) {
    ++checks;
    if (!condition) throw std::runtime_error(description);
}
Position position(std::string_view fen) {
    Position p; std::string error;
    check(p.set_fen(fen, &error), "Fixture FEN: " + std::string(fen) + ": " + error);
    return p;
}
Move move(Position& p, std::string_view uci) {
    const Move m = p.parse_uci(uci);
    check(bool(m), "Fixture move must be legal: " + std::string(uci) + " in " + p.fen());
    return m;
}
bool legal(Position p, Move m) {
    const auto moves = p.legal_moves();
    return std::find(moves.begin(), moves.end(), m) != moves.end();
}
void check_pv(Position p, const SearchResult& r) {
    check(!r.pv.empty(), "Nonterminal result must carry a PV");
    check(r.best == r.pv.front(), "Best move must head PV");
    for (Move m : r.pv) {
        check(legal(p, m), "PV move must be legal: " + m.uci() + " in " + p.fen());
        Undo undo; p.make(m, undo);
    }
}
SearchResult search(Searcher& s, Position p, int depth, std::uint64_t nodes = 0) {
    SearchLimits limits; limits.depth = depth; limits.nodes = nodes;
    std::atomic_bool stop{false};
    return s.search(p, limits, stop);
}

// Reflect ranks and swap colours; side-to-move evaluation should be unchanged.
Position reflected(const Position& p) {
    constexpr char names[] = ".PNBRQK";
    std::string fen;
    for (int rank = 7; rank >= 0; --rank) {
        int empty = 0;
        for (int file = 0; file < 8; ++file) {
            const int pc = -p.board[(7 - rank) * 8 + file];
            if (!pc) { ++empty; continue; }
            if (empty) { fen += char('0' + empty); empty = 0; }
            char c = names[type_of(pc)];
            if (pc < 0) c = char(c + 'a' - 'A');
            fen += c;
        }
        if (empty) fen += char('0' + empty);
        if (rank) fen += '/';
    }
    fen += p.side == White ? " b - - 0 1" : " w - - 0 1";
    return position(fen);
}

void evaluation_tests() {
    Position start;
    check(evaluate(start) == 8, "Symmetric starting evaluation must equal tempo bonus");
    for (const auto fen : {
        "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 7",
        "8/5pk1/2p3p1/1p1pP3/1P1P1P2/2P3K1/8/8 w - - 0 36",
        "2r2k2/2q2pp1/p2pbn1p/1p2p3/4P3/1PN1B1PP/P1PQ1PB1/3R2K1 b - - 1 20"}) {
        const auto p = position(fen);
        check(evaluate(p) == evaluate(reflected(p)), "Evaluation must respect colour/rank reflection");
        check(std::abs(evaluate(p)) <= 20000, "Static score must stay outside mate range");
    }
    auto queen = position("6k1/8/8/8/8/8/8/K2Q4 w - - 0 1");
    auto bare = position("6k1/8/8/8/8/8/8/K7 w - - 0 1");
    check(evaluate(queen) > evaluate(bare) + 700, "Extra queen must materially improve evaluation");
}

void exchange_tests() {
    struct Case { const char* fen; const char* uci; int expected; };
    for (const auto& c : std::vector<Case>{
        {"4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1", "e4d5", 100},
        {"4k3/8/4p3/3p4/4P3/8/8/4K3 w - - 0 1", "e4d5", 0},
        {"4k3/8/4p3/3p4/4Q3/8/8/4K3 w - - 0 1", "e4d5", -870},
        {"4k3/4n3/8/3p4/2B5/8/8/K3R3 w - - 0 1", "c4d5", 100},
        {"4k3/3p4/8/1B6/8/8/8/K2R4 w - - 0 1", "d1d7", 100},
        {"7k/P7/8/8/8/8/8/7K w - - 0 1", "a7a8q", 870},
        {"7k/P7/8/8/8/8/8/7K w - - 0 1", "a7a8n", 225},
        {"1r5k/P7/8/8/8/8/8/7K w - - 0 1", "a7b8q", 1375},
        {"1rr4k/P7/8/8/8/8/8/7K w - - 0 1", "a7b8q", 405},
        {"4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6", 100},
        {"3rk3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6", 0},
        {"4k3/8/8/8/8/8/8/4K2R w K - 0 1", "e1g1", 0}
    }) {
        auto p = position(c.fen);
        const auto fen = p.fen(); const auto key = p.key;
        const int got = static_exchange(p, move(p, c.uci));
        check(got == c.expected, std::string("SEE ") + c.uci + ": expected "
              + std::to_string(c.expected) + ", got " + std::to_string(got));
        check(p.fen() == fen && p.key == key && p.consistent(), "SEE must leave position unchanged");
    }
}

void terminal_tests(bool hints = false, bool direct = false) {
    Searcher s(1);
    SearchOptions options; options.hash_move_hints = hints; options.direct_legal = direct; s.set_options(options);
    const auto mate = position("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1");
    auto r = search(s, mate, 3);
    check(!r.best && r.score == -MateScore, "Root checkmate must have no move and a mate score");
    auto stale = position("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1");
    r = search(s, stale, 3);
    check(!r.best && r.score == 0, "Root stalemate must score draw");
    auto fifty_mate = position("7k/6Q1/6K1/8/8/8/8/8 b - - 100 51");
    r = search(s, fifty_mate, 3);
    check(!r.best && r.score == -MateScore, "Checkmate must precede fifty-move draw");
    auto fifty = position("4k3/8/8/8/8/8/8/R3K3 w - - 100 51");
    r = search(s, fifty, 3);
    check(r.score == 0 && legal(fifty, r.best), "Drawn nonterminal root must retain legal fallback");
    check_pv(fifty, r);
    auto nearing_fifty = position("4k3/8/8/8/8/8/8/R3K3 w - - 99 51");
    r = search(s, nearing_fifty, 2);
    check(r.score == 0, "Non-pawn moves reaching halfmove 100 must draw inside search");
    check_pv(nearing_fifty, r);
    auto reset = position("4k3/8/8/8/8/8/P7/R3K3 w - - 99 51");
    SearchLimits pawn_limit; pawn_limit.depth = 2;
    pawn_limit.searchmoves = {move(reset, "a2a3")}; std::atomic_bool pawn_stop{false};
    r = s.search(reset, pawn_limit, pawn_stop);
    check(r.score > 100, "Pawn move must reset draw clock before draw adjudication");
    check_pv(reset, r);
    auto insufficient = position("4k3/8/8/8/8/8/8/4K3 w - - 0 1");
    r = search(s, insufficient, 3);
    check(r.score == 0 && legal(insufficient, r.best), "Insufficient-material root must retain fallback");
    Position repeated;
    for (int cycle = 0; cycle < 2; ++cycle)
        for (auto uci : {"g1f3", "g8f6", "f3g1", "f6g8"}) {
            const auto m = move(repeated, uci); Undo undo; repeated.make(m, undo);
        }
    check(repeated.repetition_count() == 3, "Fixture must be third repetition");
    r = search(s, repeated, 3);
    check(r.score == 0 && legal(repeated, r.best), "Threefold root draw must retain legal fallback");
    Position contextual;
    for (auto uci : {"g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1"}) {
        const auto m = move(contextual, uci); Undo undo; contextual.make(m, undo);
    }
    SearchLimits repetition_limit; repetition_limit.depth = 3;
    repetition_limit.searchmoves = {move(contextual, "f6g8")}; std::atomic_bool repetition_stop{false};
    r = s.search(contextual, repetition_limit, repetition_stop);
    check(r.score == 0, "Threefold history must be recognized below the root");
    auto unhistoried = position(contextual.fen());
    Searcher fresh(1);
    fresh.set_options(options);
    const auto warmed = s.search(unhistoried, repetition_limit, repetition_stop);
    const auto fresh_result = fresh.search(unhistoried, repetition_limit, repetition_stop);
    check(warmed.score == fresh_result.score && warmed.best == fresh_result.best,
          "History-dependent draw must not poison a later history-free TT result");
    // The reverse direction also matters: an unrelated history-free bound must
    // not hide a repetition escape in a later historical search.
    auto escape = position("7r/5k2/8/8/6PQ/p2p2PQ/4n3/K1n5 w - - 0 1");
    for (auto uci : {"a1b1", "h8b8", "b1a1", "b8h8", "a1b1"}) {
        const auto m = move(escape, uci); Undo undo; escape.make(m, undo);
    }
    auto checking = escape;
    { const auto m = move(checking, "h8b8"); Undo undo; checking.make(m, undo); }
    const auto evasions = checking.legal_moves();
    check(checking.in_check() && evasions.size() == 1 && evasions[0].uci() == "b1a1",
          "Repetition escape must force White's only check evasion");
    auto third = checking;
    for (auto uci : {"b1a1", "b8h8"}) {
        const auto m = move(third, uci); Undo undo; third.make(m, undo);
    }
    check(third.repetition_count() == 3, "Forced escape must reach third repetition");
    Searcher warm_escape(16), fresh_escape(16);
    warm_escape.set_options(options); fresh_escape.set_options(options);
    search(warm_escape, position(checking.fen()), 1);
    SearchLimits escape_limit; escape_limit.depth = 2;
    escape_limit.searchmoves = {move(escape, "h8h4"), move(escape, "h8b8")};
    const auto escaped_warm = warm_escape.search(escape, escape_limit, repetition_stop);
    const auto escaped_fresh = fresh_escape.search(escape, escape_limit, repetition_stop);
    check(escaped_warm.score == 0 && escaped_fresh.score == 0
          && escaped_warm.best.uci() == "h8b8" && escaped_fresh.best.uci() == "h8b8",
          "History-free TT bound must not hide a forced repetition draw");
    check_pv(escape, escaped_warm); check_pv(escape, escaped_fresh);
    auto mate_in_one = position("7k/5Q2/6K1/8/8/8/8/8 w - - 99 51");
    r = search(s, mate_in_one, 3);
    check(r.score == MateScore - 1, "Mate on halfmove 100 must outrank draw");
    Undo undo; mate_in_one.make(r.best, undo);
    check(mate_in_one.in_check() && mate_in_one.legal_moves().empty(), "Mate score must correspond to actual mate");
}

void limit_and_pv_tests() {
    {
        Searcher delayed(1);
        Position start;
        SearchLimits expired;
        expired.movetime_ms = 20;
        expired.overhead_ms = 0;
        expired.received_at = std::chrono::steady_clock::now() - std::chrono::seconds(1);
        std::atomic_bool stop{false};
        const auto result = delayed.search(start, expired, stop);
        check(result.nodes == 0 && result.depth == 0,
              "Worker dispatch delay must consume an already-expired search budget");
        check(legal(start, result.best), "Expired dispatch deadline must retain a legal fallback");
    }
    Position p;
    Searcher first(2), second(2);
    const auto a = search(first, p, 3), b = search(second, p, 3);
    check(a.best == b.best && a.score == b.score && a.nodes == b.nodes && a.pv == b.pv,
          "Fresh fixed-depth searches must be deterministic");
    check(a.depth == 3, "Depth limit must complete exactly requested depth");
    check_pv(p, a);
    for (const std::uint64_t cap : {1, 2, 40, 1000}) {
        Searcher limited(1); const auto r = search(limited, p, 20, cap);
        check(r.nodes <= cap, "Node count must obey hard node limit");
        check(legal(p, r.best), "Node-limited search must return legal fallback");
        check_pv(p, r);
    }
    SearchLimits limits; limits.depth = 30;
    std::atomic_bool stop{true};
    const auto begin = std::chrono::steady_clock::now();
    const auto stopped = first.search(p, limits, stop);
    const auto elapsed = std::chrono::steady_clock::now() - begin;
    check(stopped.nodes == 0 && legal(p, stopped.best), "Pre-stopped search must return legal fallback without nodes");
    check(elapsed < std::chrono::milliseconds(250), "Pre-stopped return must meet 250 ms bound");
    check_pv(p, stopped);
    stop = false; limits.depth = 20;
    const auto interrupted = first.search(p, limits, stop, [&](const SearchInfo& info) {
        check(info.depth == 1, "Callback-triggered stop should occur after first completed depth");
        stop = true;
    });
    check(interrupted.depth == 1 && legal(p, interrupted.best), "Callback stop must preserve completed iteration");
    check_pv(p, interrupted);
    stop = false; limits.depth = 3;
    limits.searchmoves = {move(p, "a2a3")};
    const auto restricted = first.search(p, limits, stop);
    check(restricted.best == limits.searchmoves[0], "Searchmoves must restrict root selection");
    check_pv(p, restricted);
    // A restricted root's incomplete move set does not define a globally valid
    // position score. Its fully searched descendant positions may be cached.
    limits.searchmoves.clear();
    const auto after_restriction = first.search(p, limits, stop);
    Searcher unrestricted_reference(2);
    const auto unrestricted = unrestricted_reference.search(p, limits, stop);
    check(after_restriction.score == unrestricted.score,
          "Restricted-then-unrestricted root must retain unrestricted score");
    check(legal(p, after_restriction.best), "Unrestricted warm-cache result must remain legal");
    check_pv(p, after_restriction);
    limits.searchmoves = {Move(0, 63)};
    const auto impossible = first.search(p, limits, stop);
    check(!impossible.best, "No legal restricted root move must return null move");
    first.resize_hash(1); first.clear();
    const auto cleared = search(first, p, 2);
    check(cleared.depth == 2 && legal(p, cleared.best), "Hash resize/clear must leave search usable");
}

void search_tactics_and_options() {
    const auto mate_position = position("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1");
    auto restricted_mate = position("7k/4Q3/6K1/8/8/8/8/8 w - - 0 1");
    Searcher restricted_cache(1);
    SearchLimits restricted_limit; restricted_limit.depth = 3;
    restricted_limit.searchmoves = {move(restricted_mate, "e7f7")};
    std::atomic_bool restricted_stop{false};
    const auto forced_stalemate = restricted_cache.search(restricted_mate, restricted_limit, restricted_stop);
    check(forced_stalemate.score == 0, "Restricted root may deliberately choose stalemate over available mate");
    restricted_limit.searchmoves.clear();
    const auto restored_mate = restricted_cache.search(restricted_mate, restricted_limit, restricted_stop);
    check(restored_mate.score == MateScore - 1,
          "Unrestricted search after cached restricted stalemate must recover available mate");
    check_pv(restricted_mate, restored_mate);
    Searcher warm(2);
    const auto one = search(warm, mate_position, 4);
    const auto two = search(warm, mate_position, 4);
    check(one.score == MateScore - 1 && two.score == one.score, "Warm TT must preserve mate distance");
    check_pv(mate_position, one); check_pv(mate_position, two);
    // Black has only Kh8, then Qg7#. Warm this position at the root, then
    // reach that identical board and halfmove clock one ply below another root.
    auto child = position("8/7k/5K2/6Q1/8/8/8/8 b - - 1 1");
    auto r = search(warm, child, 4);
    check(r.score == -MateScore + 2, "Forced loss must report two plies to mate");
    check_pv(child, r);
    auto parent = position("8/7k/8/5KQ1/8/8/8/8 w - - 0 1");
    SearchLimits mate_limit; mate_limit.depth = 4;
    mate_limit.searchmoves = {move(parent, "f5f6")};
    std::atomic_bool mate_stop{false};
    r = warm.search(parent, mate_limit, mate_stop);
    Searcher cold(2); const auto comparison = cold.search(parent, mate_limit, mate_stop);
    check(r.score == MateScore - 3 && r.score == comparison.score,
          "TT mate scores must agree with fresh search across positions/plies");
    check_pv(parent, r);
    auto promotion = position("7k/P7/8/8/8/8/8/7K w - - 0 1");
    r = search(cold, promotion, 2);
    check(r.best.promotion() != Empty, "Search must recognize free promotion");
    check_pv(promotion, r);
    // At depth one, the opponent is in check at the quiescence boundary and
    // has a forced quiet evasion. It must not stand pat in check or invent mate.
    auto evasion = position("6k1/8/8/8/8/8/8/4K2R w - - 0 1");
    SearchLimits limit; limit.depth = 1; limit.searchmoves = {move(evasion, "h1h8")};
    std::atomic_bool stop{false};
    r = cold.search(evasion, limit, stop);
    check(std::abs(r.score) < MateScore - MaxPly, "Quiet check evasion at quiescence boundary must not be false mate");
    check_pv(evasion, r);
    auto stalemate_child = position("7k/4Q3/8/5K2/8/8/8/8 w - - 0 1");
    limit.searchmoves = {move(stalemate_child, "e7f7")};
    r = cold.search(stalemate_child, limit, stop);
    check(r.score == 0, "Quiescence must detect stalemate before a stand-pat cutoff");
    check_pv(stalemate_child, r);
    auto tactics = position("r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 7");
    for (int mask = 0; mask < 8; ++mask) {
        Searcher variant(1); SearchOptions options;
        options.null_move = mask & 1; options.lmr = mask & 2; options.futility = mask & 4;
        variant.set_options(options);
        check(variant.options().null_move == options.null_move && variant.options().lmr == options.lmr
              && variant.options().futility == options.futility, "Search option roundtrip");
        r = search(variant, tactics, 4, 20000);
        check(legal(tactics, r.best), "Every selective option combination must return legal move");
        check_pv(tactics, r);
    }
    SearchOptions exact; exact.pvs = exact.aspiration = exact.see = false;
    Searcher plain(1); plain.set_options(exact);
    r = search(plain, mate_position, 3);
    check(r.score == MateScore - 1, "Plain alpha-beta must find mate with ordering/PVS options disabled");
}

SearchResult compare_quiescence_paths(const Position& p, const SearchLimits& limits,
                                      SearchOptions options = {}) {
    Searcher reference(1), optimized(1);
    options.fast_quiescence = false; reference.set_options(options);
    options.fast_quiescence = true; optimized.set_options(options);
    check(!reference.options().fast_quiescence && optimized.options().fast_quiescence,
          "Fast quiescence option must roundtrip independently");
    std::atomic_bool reference_stop{false}, optimized_stop{false};
    const auto old = reference.search(p, limits, reference_stop);
    const auto fast = optimized.search(p, limits, optimized_stop);
    const auto label = "Fast/reference quiescence at " + p.fen();
    check(old.score == fast.score, label + ": score mismatch");
    check(old.best == fast.best, label + ": best move mismatch");
    check(old.pv == fast.pv, label + ": PV mismatch");
    check(old.depth == fast.depth, label + ": completed depth mismatch");
    check(old.nodes == fast.nodes, label + ": exact node count mismatch");
    if (fast.best) check_pv(p, fast);
    return fast;
}

void fast_quiescence_tests() {
    check(!SearchOptions{}.fast_quiescence, "Fast quiescence must remain off by default");
    SearchLimits modest; modest.depth = 2; modest.nodes = 4000;
    for (const auto fen : {
        StartFen,
        std::string_view("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
        std::string_view("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"),
        std::string_view("2r2k2/2q2pp1/p2pbn1p/1p2p3/4P3/1PN1B1PP/P1PQ1PB1/3R2K1 b - - 1 20"),
        std::string_view("7k/P7/8/8/8/8/8/7K w - - 0 1"),
        std::string_view("1r5k/P7/8/8/8/8/8/7K w - - 0 1"),
        std::string_view("3rk3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"),
        std::string_view("4k3/8/8/K2pP2r/8/8/8/8 w - d6 0 1"),
        std::string_view("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"),
        std::string_view("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")})
        compare_quiescence_paths(position(fen), modest);

    // Empty tactical generation can mean either quiet legal moves or stalemate.
    // Exercise the latter exactly at a depth-one quiescence boundary.
    auto stale = position("7k/4Q3/8/5K2/8/8/8/8 w - - 0 1");
    SearchLimits boundary; boundary.depth = 1;
    boundary.searchmoves = {move(stale, "e7f7")};
    const auto stalemate = compare_quiescence_paths(stale, boundary);
    check(stalemate.score == 0, "Fast quiescence must detect stalemate before stand pat");

    // ...Kf7 is the only evasion after Rh8+, and it is a quiet king move.
    auto check_evasion = position("6k1/6B1/5P2/8/8/8/8/4K2R w - - 0 1");
    boundary.searchmoves = {move(check_evasion, "h1h8")};
    auto checked = check_evasion;
    { Undo undo; checked.make(boundary.searchmoves.front(), undo); }
    const auto evasions = checked.legal_moves();
    check(checked.in_check() && evasions.size() == 1 && evasions[0].uci() == "g8f7"
          && !evasions[0].capture(), "Quiet-evasion fixture must force ...Kf7");
    const auto evaded = compare_quiescence_paths(check_evasion, boundary);
    check(std::abs(evaded.score) < MateScore - MaxPly,
          "Fast quiescence must search quiet check evasions rather than invent mate");

    // Quiet promotion belongs in quiescence even when there is no capture.
    auto promotion = position("7k/8/8/8/8/8/p7/7K w - - 0 1");
    boundary.searchmoves = {move(promotion, "h1g1")};
    const auto promoted = compare_quiescence_paths(promotion, boundary);
    check(promoted.score < -500, "Quiescence must see the opponent's quiet promotion");

    // A just-created en passant capture must be available to the q search.
    auto ep = position("4k3/8/8/8/3p4/8/4P3/4K3 w - - 0 1");
    boundary.searchmoves = {move(ep, "e2e4")};
    compare_quiescence_paths(ep, boundary);

    // Legal deterministic walks provide changing occupancy and real reversible
    // histories. The fixed node cap bounds pathological tactical continuations.
    Position random_position;
    std::uint64_t random = 0x4f7269656e745f71ULL;
    for (int ply = 1; ply <= 96; ++ply) {
        auto moves = random_position.legal_moves();
        if (moves.empty() || random_position.halfmove >= 100 || random_position.repetition_count() >= 3) {
            random_position = Position{}; moves = random_position.legal_moves();
        }
        random ^= random << 13; random ^= random >> 7; random ^= random << 17;
        const auto selected = moves[int(random % std::uint64_t(moves.size()))];
        Undo undo; random_position.make(selected, undo);
        if (ply % 8 == 0) {
            SearchLimits bounded; bounded.depth = 2; bounded.nodes = 2000;
            compare_quiescence_paths(random_position, bounded);
        }
    }
    auto tactics = position("r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 7");
    for (int mask = 0; mask < 8; ++mask) {
        SearchOptions options;
        options.null_move = mask & 1; options.lmr = mask & 2; options.futility = mask & 4;
        SearchLimits bounded; bounded.depth = 4; bounded.nodes = 3000;
        compare_quiescence_paths(tactics, bounded, options);
    }
}

void hash_hint_tests() {
    check(!SearchOptions{}.hash_move_hints, "Hash move hints must remain disabled until measured");
    for (const auto fen : {
        StartFen,
        std::string_view("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
        std::string_view("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"),
        std::string_view("2r2k2/2q2pp1/p2pbn1p/1p2p3/4P3/1PN1B1PP/P1PQ1PB1/3R2K1 b - - 1 20"),
        std::string_view("3rk3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"),
        std::string_view("1r5k/P7/8/8/8/8/8/7K w - - 0 1")}) {
        const auto p = position(fen);
        Searcher reference(1), candidate(1);
        SearchOptions options; options.hash_move_hints = true; candidate.set_options(options);
        const auto original = search(reference, p, 3), hinted = search(candidate, p, 3);
        check(original.depth == 3 && hinted.depth == 3, "Hint comparison must finish fixed depth");
        check(original.score == hinted.score, "Move-only hints must preserve exact fixed-depth score");
        check_pv(p, hinted);
    }
    terminal_tests(true);
}

void compare_direct_paths(const Position& p, const SearchLimits& limits, SearchOptions options = {}) {
    Searcher reference(1), candidate(1);
    options.direct_legal = false; reference.set_options(options);
    options.direct_legal = true; candidate.set_options(options);
    std::atomic_bool stop{false};
    const auto a = reference.search(p, limits, stop), b = candidate.search(p, limits, stop);
    check(a.score == b.score && a.best == b.best && a.depth == b.depth && a.nodes == b.nodes && a.pv == b.pv,
          "Direct legality must preserve exact reference search work and result");
    if (b.best) check_pv(p, b);
}

void direct_legal_tests() {
    check(!SearchOptions{}.direct_legal, "Direct legality must remain disabled until measured");
    for (const auto fen : {
        StartFen,
        std::string_view("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
        std::string_view("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"),
        std::string_view("1r5k/P7/8/8/8/8/8/7K w - - 0 1"),
        std::string_view("4k3/8/8/3pP3/4K3/8/8/8 w - d6 0 1"),
        std::string_view("k7/8/8/r4pPK/8/8/8/8 w - f6 0 1"),
        std::string_view("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"),
        std::string_view("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")}) {
        SearchLimits bounded; bounded.depth = 3; bounded.nodes = 4000;
        compare_direct_paths(position(fen), bounded);
    }
    const auto tactics = position("r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 7");
    for (int mask = 0; mask < 32; ++mask) {
        SearchOptions options;
        options.null_move = mask & 1; options.lmr = mask & 2; options.futility = mask & 4;
        options.fast_quiescence = mask & 8; options.hash_move_hints = mask & 16;
        SearchLimits bounded; bounded.depth = 4; bounded.nodes = 3000;
        compare_direct_paths(tactics, bounded, options);
    }
    terminal_tests(false, true);
}
}

int main() {
    try {
        evaluation_tests(); exchange_tests(); terminal_tests();
        limit_and_pv_tests(); search_tactics_and_options(); fast_quiescence_tests(); hash_hint_tests(); direct_legal_tests();
        std::cout << "Search/evaluation: " << checks << " checks passed\n";
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::cerr << "Search/evaluation failure after " << checks << " checks: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
