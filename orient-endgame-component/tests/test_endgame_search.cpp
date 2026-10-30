#include "orient/search.hpp"
#include "orient/tablebases.hpp"
#include <atomic>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>

using namespace orient;
void require(bool value, const char* text) { if (!value) throw std::runtime_error(text); }
Position position(const std::string& fen) {
    Position p; std::string error;
    if (!p.set_fen(fen, &error)) throw std::runtime_error(error + ": " + fen);
    return p;
}
SearchResult run(Searcher& search, Position p, int depth = 3, Move only = {}) {
    SearchLimits limits; limits.depth = depth;
    if (only) limits.searchmoves = {only};
    std::atomic_bool stop{false};
    return search.search(std::move(p), limits, stop);
}
Position played(const std::string& fen, const char* moves) {
    auto p = position(fen);
    std::istringstream input(moves);
    for (std::string text; input >> text;) {
        const Move move = p.parse_uci(text);
        require(bool(move), "history regression transcript contains an illegal move");
        Undo undo; p.make(move, undo);
    }
    return p;
}
Position game53_before_loss() {
    // Actual initial FEN and all 36 recorded plies, including the zeroing
    // capture and earlier repetitions. Resetting only the final FEN misses the bug.
    auto p = played("5r2/8/8/8/4B3/2k5/6P1/Kq6 w - - 0 1",
        "e4b1 f8f1 g2g4 c3b3 g4g5 f1g1 g5g6 b3a3 g6g7 g1g7 "
        "b1d3 a3b3 d3e4 g7g1 e4b1 b3c3 a1a2 g1g2 a2a1 g2g1 "
        "a1a2 g1g2 a2a1 g2e2 b1g6 e2e1 a1a2 e1e2 a2a1 e2e3 "
        "a1b1 e3e1 b1a2 e1e5 a2b1 e5b5");
    require(p.fen() == "8/8/6B1/1r6/8/2k5/8/1K6 w - - 26 19",
            "recorded game53 position or clock changed");
    require(p.history.size() == 37 && p.repetition_count() == 1,
            "recorded game53 must retain its full history despite a unique current position");
    return p;
}
void history_safe_draws(const std::shared_ptr<Tablebases>& tables) {
    auto original = game53_before_loss();
    const auto root = tables->probe_root(original);
    require(root.status == ProbeStatus::Success && root.wdl == 2,
            "game53 regression needs a covered drawing root");
    const Move loses = original.parse_uci("b1c1");
    const Move draws = original.parse_uci("b1a2");
    bool confirmed_loss = false;
    for (const auto& move : root.moves) if (move.move == loses) confirmed_loss = move.wdl == 0;
    require(confirmed_loss, "recorded Kc1 loss must remain a losing tablebase alternative");
    for (bool direct : {false, true}) {
        for (bool null_move : {false, true}) {
            Searcher search(1), plain(1);
            SearchOptions options; options.direct_legal = direct; options.null_move = null_move;
            search.set_options(options); plain.set_options(options); search.set_tablebases(tables);
            int callbacks = 0;
            SearchLimits limits; limits.depth = 8;
            std::atomic_bool stop{false};
            auto r = search.search(original, limits, stop, [&](const SearchInfo& info) {
                ++callbacks;
                require(info.depth == 0 && info.score == 0 && info.tablebase_hits > 0,
                        "history drawing guidance must report only its certified draw");
            });
            require((r.best.uci() == "b1a1" || r.best == draws) && r.score == 0
                    && r.depth == 0 && r.nodes == 0 && r.tablebase_hits > 0 && callbacks == 1,
                    "actual game53 history must keep a drawing king move instead of 19.Kc1");
            r = run(search, original, 1, draws);
            require(r.best == draws && r.score == 0 && r.depth == 0,
                    "searchmoves must allow its requested certified drawing move");
            search.clear(); plain.clear();
            r = run(search, original, 1, loses);
            const auto reference = run(plain, original, 1, loses);
            require(r.best == loses && r.depth > 0 && r.nodes > 0 && r.score == reference.score
                    && r.nodes == reference.nodes,
                    "only a losing-labelled searchmove must retain ordinary history-aware search");
            stop.store(true);
            r = search.search(original, limits, stop);
            require(bool(original.parse_uci(r.best.uci())) && r.tablebase_hits == 0,
                    "already-stopped history search must retain its legal fallback");
            stop.store(false); limits.movetime_ms = 1;
            limits.received_at = std::chrono::steady_clock::now() - std::chrono::seconds(1);
            r = search.search(original, limits, stop);
            require(bool(original.parse_uci(r.best.uci())) && r.tablebase_hits == 0,
                    "expired budget must not start history tablebase guidance");
        }
    }

    // A history-free loss can be an actual draw. The only requested move below
    // recreates the losing child's third occurrence, so its history must win
    // over the table label. All transitions in this transcript are legal.
    auto rescued = played("8/8/6B1/1r6/8/2k5/8/2K5 b - - 0 1",
                          "b5h5 c1b1 h5b5 b1c1 b5h5 c1b1 h5b5");
    require(rescued.repetition_count() == 2, "rescue root must not already be a terminal draw");
    const Move rescue = rescued.parse_uci("b1c1");
    const auto rescued_root = tables->probe_root(rescued);
    bool loses_without_history = false;
    for (const auto& move : rescued_root.moves)
        if (move.move == rescue) loses_without_history = move.wdl == 0;
    require(rescued_root.wdl == 2 && loses_without_history,
            "rescue move must have a genuinely losing history-free label");
    auto child = rescued; Undo undo; child.make(rescue, undo);
    require(child.repetition_count() == 3, "rescue move must actually create a legal threefold draw");
    Searcher search(1); search.set_tablebases(tables);
    auto r = run(search, rescued, 1, rescue);
    require(r.best == rescue && r.score == 0 && r.depth == 0 && r.nodes == 0,
            "actual immediate repetition draw must survive a losing table label and searchmoves restriction");

    auto winning = played("7k/8/8/8/8/8/Q7/4K3 w - - 0 1", "a2a3 h8g8 a3a2 g8h8");
    auto losing = played("7k/8/8/8/8/Q7/8/4K3 b - - 0 1", "h8g8 a3a2 g8h8 a2a3");
    for (const auto& p : {winning, losing}) {
        r = run(search, p, 1);
        require(r.depth > 0 && r.nodes > 0 && r.tablebase_hits == 0,
                "decisive repeated roots must keep ordinary history-aware search");
    }
    auto threefold = played("7k/8/8/8/8/8/Q7/4K3 w - - 0 1",
                           "a2a3 h8g8 a3a2 g8h8 a2a3 h8g8 a3a2 g8h8");
    require(threefold.repetition_count() == 3, "third repetition fixture");
    r = run(search, threefold, 1);
    require(r.score == 0 && r.nodes == 0 && r.tablebase_hits == 0,
            "current threefold draw takes precedence over a winning tablebase value");

    auto cursed = played("7k/8/8/8/8/8/Q7/4K3 w - - 95 1", "a2a3 h8g8 a3a2 g8h8");
    auto blessed = played("7k/8/8/8/8/Q7/8/4K3 b - - 95 1", "h8g8 a3a2 g8h8 a2a3");
    require(tables->probe_root(cursed).wdl == 3 && tables->probe_root(blessed).wdl == 1,
            "clock-boundary fixtures must exercise cursed and blessed values");
    for (const auto& p : {cursed, blessed}) {
        r = run(search, p, 1);
        require(r.score == 0 && r.depth > 0 && r.nodes > 0 && r.tablebase_hits == 0,
                "cursed/blessed repeated roots retain conservative history-aware fallback");
    }
}
int main(int argc, char** argv) {
    try {
        const char* env = std::getenv("ORIENT_SYZYGY_PATH");
        if (argc < 2 && !env) { std::cout << "Set ORIENT_SYZYGY_PATH for real-data endgame tests\n"; return 77; }
        auto tables = std::make_shared<Tablebases>(argc > 1 ? argv[1] : env, 4);
        require(tables->largest() == 5, "complete five-piece tables required");
        Searcher search(1), reference(1); search.set_tablebases(tables);
        auto queen = position("6k1/8/8/8/8/8/8/K2Q4 w - - 0 1");
        auto r = run(search, queen);
        require(r.tablebase_hits > 0 && r.score == TablebaseScore, "root must return proven win, not invented mate");
        require(queen.parse_uci(r.best.uci()) == r.best, "root move must be legal");
        auto mate = position("7k/8/5KQ1/8/8/8/8/8 w - - 0 1");
        r = run(search, mate);
        require(r.score == MateScore - 1, "actual mate in one takes precedence over DTZ");
        auto terminal = position("7k/6Q1/6K1/8/8/8/8/8 b - - 100 51");
        r = run(search, terminal);
        require(!r.best && r.score == -MateScore, "checkmate precedes rule-50 draw");
        auto stale = position("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1");
        r = run(search, stale); require(!r.best && r.score == 0, "stalemate is a terminal draw");
        auto near = position("4k3/8/8/8/8/8/8/R3K3 w - - 99 51");
        r = run(search, near); require(r.score == 0, "quiet rule-50 boundary cannot become a tablebase win");
        auto under = position("8/1P6/k7/8/1K6/8/8/8 w - - 0 1");
        r = run(search, under, 3, under.parse_uci("b7b8r"));
        require(r.best.uci() == "b7b8r" && r.score == TablebaseScore, "restricted rook promotion must win");
        r = run(search, under, 3, under.parse_uci("b7b8q"));
        require(r.best.uci() == "b7b8q" && r.score == 0, "restricted queen promotion must stalemate");
        auto ep = position("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1");
        auto capture = ep.parse_uci("e5d6"); require(bool(capture), "EP fixture legal");
        r = run(search, ep, 2, capture); require(r.best == capture && r.tablebase_hits > 0, "EP flag must survive table translation");
        auto rights = position("4k3/8/8/8/8/8/8/4K2R w K - 0 1");
        r = run(search, rights, 1); require(r.tablebase_hits == 0, "castling positions must use normal search");
        auto repeated = position("7k/8/8/8/8/8/Q7/4K3 w - - 0 1");
        for (auto text : {"a2a3", "h8g8", "a3a2", "g8h8"}) {
            const auto m = repeated.parse_uci(text); require(bool(m), "repetition move legal");
            Undo undo; repeated.make(m, undo);
        }
        auto fresh = position(repeated.fen());
        require(run(search, fresh, 1).tablebase_hits > 0, "history-free fixture is covered");
        require(run(search, repeated, 1).tablebase_hits == 0, "prior repetition must preserve history-aware search");
        history_safe_draws(tables);
        {
            Searcher full_legal(1), direct_legal(1);
            full_legal.set_tablebases(tables); direct_legal.set_tablebases(tables);
            SearchOptions options; options.direct_legal = true;
            direct_legal.set_options(options);
            const auto same = [&](const Position& p, int depth, Move only = {}) {
                full_legal.clear(); direct_legal.clear();
                const auto a = run(full_legal, p, depth, only);
                const auto b = run(direct_legal, p, depth, only);
                require(a.best == b.best && a.score == b.score && a.depth == b.depth
                        && a.nodes == b.nodes && a.pv == b.pv && a.tablebase_hits == b.tablebase_hits,
                        "Direct legal root reuse changed search result or restricted move handling");
            };
            for (const auto& p : {queen, mate, terminal, stale, near, fresh, repeated, rights}) same(p, 1);
            same(under, 3, under.parse_uci("b7b8r"));
            same(under, 3, under.parse_uci("b7b8q"));
            same(ep, 2, capture);
        }
        search.set_tablebases(tables, 0);
        const auto off = run(search, queen, 4), plain = run(reference, queen, 4);
        require(off.best == plain.best && off.score == plain.score && off.nodes == plain.nodes && off.tablebase_hits == 0,
                "disabled tables must preserve search exactly");
        search.set_tablebases(std::make_shared<Tablebases>("/unavailable/orient/tablebases"));
        const auto missing = run(search, queen, 4);
        reference.clear(); const auto ordinary = run(reference, queen, 4);
        require(missing.best == ordinary.best && missing.score == ordinary.score && missing.nodes == ordinary.nodes,
                "unavailable tables must preserve ordinary search");
        search.set_tablebases(tables);
        std::atomic_bool stop{true}; SearchLimits limits; limits.depth = 32;
        r = search.search(queen, limits, stop);
        require(bool(queen.parse_uci(r.best.uci())) && r.tablebase_hits == 0, "already stopped search retains legal fallback");
        std::cout << "Endgame root, rule, history, restriction and fallback checks passed\n";
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
