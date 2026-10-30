// This translation unit includes our own implementation so a friend can test a
// narrow internal window without adding a production search-window API. The
// static library supplies rules/evaluation; its search object is not needed.
#include "../src/search.cpp"
#include <cstdlib>
#include <iostream>
#include <stdexcept>

namespace orient {
struct SearchTestAccess {
    static void hash_budget_and_hints() {
        Searcher searcher(64);
        for (std::size_t mb : {1, 3, 16, 2, 64, 1}) {
            searcher.resize_hash(mb);
            auto& search = *searcher.impl_;
            const auto allocated = search.table.capacity() * sizeof(Searcher::Impl::Entry)
                                 + search.hints.capacity() * sizeof(Searcher::Impl::HintEntry);
            if (allocated > mb * 1024 * 1024)
                throw std::runtime_error("Score and hint allocation exceeds requested Hash budget");
        }
        Position a, b;
        for (auto uci : {"g1f3", "g8f6", "b1c3", "b8c6"}) {
            const auto move = a.parse_uci(uci); Undo undo; a.make(move, undo);
        }
        for (auto uci : {"b1c3", "b8c6", "g1f3", "g8f6"}) {
            const auto move = b.parse_uci(uci); Undo undo; b.make(move, undo);
        }
        if (a.key != b.key || table_key(a, history_context(a)) == table_key(b, history_context(b)))
            throw std::runtime_error("Hint fixture must transpose with distinct score histories");
        auto& search = *searcher.impl_;
        const auto move = a.parse_uci("e2e4");
        search.save_hint(a.key, 4, move);
        if (search.move_hint(b.key) != move)
            throw std::runtime_error("Move hint must survive a different reversible history");
        Searcher::Impl::Ordered ordered(search, b, b.legal_moves(), search.move_hint(b.key), 0);
        if (ordered.next(0) != move)
            throw std::runtime_error("Transposed legal hint did not receive ordering priority");
        // A stale/malformed hint may never add a move to the legal list.
        const Move illegal(12, 36);
        search.save_hint(b.key, 5, illegal);
        Searcher::Impl::Ordered poisoned(search, b, b.legal_moves(), search.move_hint(b.key), 0);
        for (int i = 0; i < poisoned.moves.size(); ++i)
            if (poisoned.next(i) == illegal)
                throw std::runtime_error("Illegal hint entered the searched move list");
        searcher.clear();
        if (search.move_hint(a.key)) throw std::runtime_error("Clear Hash retained a move hint");
        search.save_hint(a.key, 4, move); searcher.resize_hash(2);
        if (search.move_hint(a.key)) throw std::runtime_error("Hash resize retained a move hint");
        std::cout << "Hash allocation, transposed hints and legal-list isolation passed\n";
    }
    static void clock_budget_boundaries() {
        Searcher searcher(1);
        auto& search = *searcher.impl_;
        search.limits = {};
        search.limits.overhead_ms = 0;
        search.limits.wtime_ms = 1000;
        search.limits.winc_ms = std::int64_t(1) << 62;
        search.limits.movestogo = 1;
        search.budget(White);
        if (search.soft_ms != 1000 || search.hard_ms != 1000)
            throw std::runtime_error("Large increment overflowed the available clock budget");
        search.limits.wtime_ms = std::numeric_limits<std::int64_t>::max();
        search.limits.winc_ms = 0;
        search.limits.movestogo = 2;
        search.budget(White);
        if (search.soft_ms != std::numeric_limits<std::int64_t>::max() / 2
            || search.hard_ms != search.limits.wtime_ms)
            throw std::runtime_error("Large soft budget overflowed the hard clock budget");
        search.limits.winc_ms = std::numeric_limits<std::int64_t>::max();
        search.limits.movestogo = 1;
        search.budget(White);
        if (search.soft_ms != search.limits.wtime_ms || search.hard_ms != search.limits.wtime_ms)
            throw std::runtime_error("Remaining clock plus increment overflowed the allocation");
        search.limits.wtime_ms = 1000;
        search.limits.winc_ms = 7;
        search.limits.movestogo = 30;
        search.budget(White);
        if (search.soft_ms != 38 || search.hard_ms != 114)
            throw std::runtime_error("Safe clock arithmetic changed the ordinary time budget");
        search.limits.btime_ms = 900;
        search.limits.binc_ms = std::int64_t(1) << 62;
        search.budget(Black);
        if (search.soft_ms != 900 || search.hard_ms != 900)
            throw std::runtime_error("Black increment overflowed the available clock budget");
        std::cout << "Full-range clock budget arithmetic passed\n";
    }
    static int narrow(Position position, Move first, bool futility) {
        Searcher searcher(1);
        std::atomic_bool stop{false};
        Position child = position;
        Undo undo; child.make(first, undo);
        SearchLimits warm; warm.depth = 1;
        const auto mate = searcher.search(child, warm, stop);
        if (mate.score != MateScore - 1)
            throw std::runtime_error("Expected genuine child mate to prime the table");
        auto& search = *searcher.impl_;
        search.options.futility = futility;
        search.killers = {}; search.history = {}; search.aborted = false;
        search.nodes = 0; search.limits.nodes = 50000; search.hard_ms = 0;
        search.pv_length.fill(0); search.stop = &stop;
        search.repetition_context[1] = history_context(position);
        return search.negamax(position, 2, -500, -499, 1, false, false, false).score;
    }
};
}

bool can_mate_in_one(orient::Position position) {
    for (auto move : position.legal_moves()) {
        orient::Undo undo; position.make(move, undo);
        const bool mate = position.in_check() && position.legal_moves().empty();
        position.unmake(move, undo);
        if (mate) return true;
    }
    return false;
}

int main() {
    try {
        using namespace orient;
        SearchTestAccess::hash_budget_and_hints();
        SearchTestAccess::clock_budget_boundaries();
        Position position;
        if (!position.set_fen("1Q6/2R5/8/8/8/5K2/8/7k b - - 0 1"))
            throw std::runtime_error("Invalid regression FEN");
        const auto first = position.parse_uci("h1g1");
        const auto escape = position.parse_uci("h1h2");
        if (!first || !escape || position.in_check() || evaluate(position) + 260 > -500)
            throw std::runtime_error("Fixture must reach non-check futility window");
        Position child = position; Undo undo; child.make(first, undo);
        if (!can_mate_in_one(child)) throw std::runtime_error("First move must lose by mate in one");
        child = position; child.make(escape, undo);
        if (can_mate_in_one(child)) throw std::runtime_error("Quiet escape must avoid mate in one");
        const auto reference = SearchTestAccess::narrow(position, first, false);
        const auto selective = SearchTestAccess::narrow(position, first, true);
        std::cout << "Futility quiet escape: reference=" << reference << " selective=" << selective << '\n';
        if (reference <= -MateScore + MaxPly || selective != reference)
            throw std::runtime_error("Futility skipped a quiet escape and invented a losing mate bound");
        std::cout << "Pruning mate-bound regression passed\n";
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
