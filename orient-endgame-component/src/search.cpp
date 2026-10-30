#include "orient/search.hpp"
#include "orient/nnue.hpp"
#include "orient/tablebases.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cassert>
#include <chrono>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace orient {
namespace {
constexpr int Infinity = 32000;
constexpr int MateThreshold = MateScore - MaxPly;
enum Bound : std::uint8_t { NoBound, Upper, Lower, Exact };
using Clock = std::chrono::steady_clock;
struct NodeValue { int score; bool contextual_draw = false; };
int to_table(int score, int ply) {
    return score >= MateThreshold ? score + ply : score <= -MateThreshold ? score - ply : score;
}
int from_table(int score, int ply) {
    return score >= MateThreshold ? score - ply : score <= -MateThreshold ? score + ply : score;
}
std::uint64_t mixed_key(std::uint64_t key) {
    key += 0x9e3779b97f4a7c15ULL;
    key = (key ^ (key >> 30)) * 0xbf58476d1ce4e5b9ULL;
    key = (key ^ (key >> 27)) * 0x94d049bb133111ebULL;
    return key ^ (key >> 31);
}
std::uint64_t history_context(const Position& p) {
    if (p.history.empty()) return mixed_key(p.key);
    const auto count = std::min<std::size_t>(p.history.size(), std::min(p.halfmove, 100) + 1);
    std::uint64_t context = 0;
    for (std::size_t i = p.history.size() - count; i < p.history.size(); ++i)
        context += mixed_key(p.history[i]);
    return context;
}
std::uint64_t table_key(const Position& p, std::uint64_t context) {
    // A cached score depends on the clock and on earlier reversible positions:
    // a history-free forced mate may instead allow a third-repetition escape.
    return p.key ^ mixed_key(std::uint64_t(std::min(p.halfmove, 100))) ^ std::rotl(context, 23);
}
int tablebase_score(int wdl) {
    return wdl == 4 ? TablebaseScore : wdl == 0 ? -TablebaseScore : 0;
}
bool repeated_history(const Position& p) {
    const auto count = std::min(p.history.size(), std::size_t(std::min(p.halfmove, 100) + 1));
    const auto first = p.history.size() - count;
    for (std::size_t i = first; i < p.history.size(); ++i)
        for (std::size_t j = first; j < i; ++j)
            if (p.history[i] == p.history[j]) return true;
    return false;
}
}

struct Searcher::Impl {
    struct Entry {
        std::uint64_t key = 0;
        Move move;
        std::int16_t score = 0;
        std::int8_t depth = -1;
        Bound bound = NoBound;
        std::uint8_t generation = 0;
    };
    struct HintEntry {
        std::uint64_t key = 0;
        Move move;
        std::int8_t depth = -1;
        std::uint8_t generation = 0;
    };
    std::vector<Entry> table;
    std::vector<HintEntry> hints;
    std::size_t mask = 0;
    std::size_t hint_mask = 0;
    std::uint8_t generation = 0;
    SearchOptions options;
    std::shared_ptr<const NeuralNetwork> network;
    std::shared_ptr<Tablebases> tablebases;
    int tablebase_limit = 5;
    std::uint64_t tablebase_hits = 0;
    std::array<NeuralNetwork::Accumulator, MaxPly> accumulators{};
    std::array<std::uint64_t, MaxPly> repetition_context{};
    std::array<std::array<std::array<int, 64>, 64>, 2> history{};
    std::array<std::array<Move, 2>, MaxPly> killers{};
    std::array<std::array<Move, MaxPly>, MaxPly> pv{};
    std::array<int, MaxPly> pv_length{};
    std::atomic_bool* stop = nullptr;
    SearchLimits limits;
    Clock::time_point start;
    std::int64_t hard_ms = 0, soft_ms = 0;
    std::uint64_t nodes = 0;
    int seldepth = 0;
    bool aborted = false;
    std::vector<Move> root_moves;

    explicit Impl(std::size_t mb) { resize(mb); }
    MoveList generate_moves(Position& p, bool tactical = false) const {
        return options.direct_legal ? p.legal_moves_direct(tactical) : p.legal_moves(tactical);
    }
    bool has_legal(Position& p) const {
        return options.direct_legal ? p.has_legal_move_direct() : p.has_legal_move();
    }
    bool tablebase_eligible(const Position& p) const {
        return tablebases && tablebase_limit > 0
            && std::popcount(p.occupancy()) <= tablebase_limit;
    }
    bool probe_outcome(const Position& p, int ply, bool null_branch, NodeValue& value) {
        // WDL has no reversible-history/clock input. Only a real zeroing move
        // (or a fresh root at clock zero) makes that shortcut history independent.
        if (ply == 0 || null_branch || p.halfmove != 0 || !tablebase_eligible(p)) return false;
        const auto probe = tablebases->probe_wdl(p);
        if (stop->load(std::memory_order_relaxed) || (hard_ms && elapsed() >= hard_ms)) {
            aborted = true; value = {0}; return true;
        }
        if (probe.status != ProbeStatus::Success) return false;
        ++tablebase_hits;
        value = {tablebase_score(probe.wdl)};
        return true;
    }
    int evaluate_position(const Position& p, int ply) const {
        return network ? network->evaluate(accumulators[ply], p.side) : evaluate(p);
    }
    void update_child_state(const Position& after, Move move, const Undo& undo, int ply,
                            [[maybe_unused]] bool null_branch) {
        const auto current = mixed_key(after.key);
        repetition_context[ply + 1] = after.halfmove == 0 ? current : repetition_context[ply] + current;
        // Null searches intentionally omit their synthetic move from history.
        // Real nodes past the move-count limit return before probing the table.
        assert(null_branch || after.halfmove > 100
               || repetition_context[ply + 1] == history_context(after));
        if (network) accumulators[ply + 1] = network->update(accumulators[ply], after, move, undo);
    }
    void resize(std::size_t mb) {
        const std::size_t maximum = std::numeric_limits<std::size_t>::max() / (1024 * 1024);
        mb = std::clamp<std::size_t>(mb, 1, maximum);
        const std::size_t bytes = mb * 1024 * 1024;
        // Both tables share the advertised Hash budget. For power-of-two MiB
        // settings, the score table keeps its previous capacity; hints occupy
        // the unused quarter. Reallocate so shrinking also releases old memory.
        const std::size_t wanted = (bytes - bytes / 4) / sizeof(Entry);
        const std::size_t count = std::bit_floor(std::max<std::size_t>(1024, wanted));
        const std::size_t hint_count = std::bit_floor(bytes / 4 / sizeof(HintEntry));
        std::vector<Entry>(count).swap(table); mask = count - 1;
        std::vector<HintEntry>(hint_count).swap(hints); hint_mask = hint_count - 1;
    }
    std::int64_t elapsed() const {
        return std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - start).count();
    }
    bool visit(int ply) {
        if (aborted || stop->load(std::memory_order_relaxed)
            || (limits.nodes && nodes >= limits.nodes)
            || ((nodes & 63) == 0 && hard_ms && elapsed() >= hard_ms)) {
            aborted = true; return false;
        }
        ++nodes; seldepth = std::max(seldepth, ply); return true;
    }
    void budget(Color side) {
        hard_ms = soft_ms = 0;
        if (limits.infinite) return;
        const auto overhead = std::max(0, limits.overhead_ms);
        if (limits.movetime_ms > 0) {
            hard_ms = std::max<std::int64_t>(1, limits.movetime_ms - overhead);
            soft_ms = hard_ms; return;
        }
        const auto remaining = side == White ? limits.wtime_ms : limits.btime_ms;
        const auto increment = side == White ? limits.winc_ms : limits.binc_ms;
        if (remaining <= 0) return;
        const auto available = std::max<std::int64_t>(1, remaining - overhead);
        const int horizon = limits.movestogo > 0 ? limits.movestogo : 30;
        // Direct API callers may supply the full int64 clock range. Compute
        // floor(3 * increment / 4) without multiplying the unbounded input,
        // then cap the sum and hard-budget multiplication before they overflow.
        const auto nonnegative_increment = std::max<std::int64_t>(0, increment);
        const auto increment_budget = nonnegative_increment / 4 * 3
                                    + nonnegative_increment % 4 * 3 / 4;
        const auto base = available / horizon;
        soft_ms = increment_budget >= available - base ? available
            : std::max<std::int64_t>(1, base + increment_budget);
        hard_ms = soft_ms > available / 3 ? available : 3 * soft_ms;
    }
    void save(std::uint64_t key, int depth, int score, Bound bound, Move best, int ply) {
        Entry& e = table[key & mask];
        if (e.bound == NoBound || e.key == key || e.generation != generation || depth + 3 >= e.depth) {
            if (e.key != key || best) e.move = best;
            e.key = key; e.depth = std::int8_t(std::min(depth, 127));
            e.score = std::int16_t(to_table(score, ply)); e.bound = bound; e.generation = generation;
        }
    }
    Move move_hint(std::uint64_t key) const {
        const HintEntry& entry = hints[key & hint_mask];
        return entry.depth >= 0 && entry.key == key ? entry.move : Move{};
    }
    void save_hint(std::uint64_t key, int depth, Move move) {
        HintEntry& entry = hints[key & hint_mask];
        if (entry.depth < 0 || entry.generation != generation || depth >= entry.depth) {
            entry.key = key; entry.move = move;
            entry.depth = std::int8_t(std::min(depth, 127)); entry.generation = generation;
        }
    }
    bool draw(Position& p, int ply, bool null_branch, bool check, NodeValue& value) {
        const bool contextual = !null_branch && (p.halfmove >= 100 || p.repetition_count() >= 3);
        if (!contextual && !p.insufficient_material()) return false;
        // Checkmate ends the game before a move-count/repetition draw can be claimed.
        if (check && generate_moves(p).empty()) { value = {-MateScore + ply, false}; return true; }
        value = {0, contextual}; return true;
    }
    int move_score(const Position& p, Move m, Move hash, int ply) const {
        if (m == hash) return 200000000;
        if (m.capture() || m.promotion() != Empty) {
            constexpr std::array<int, 7> value{0, 100, 325, 335, 505, 970, 20000};
            const auto victim = m.has(Move::EnPassant) ? Pawn : type_of(p.board[m.to()]);
            const auto attacker = type_of(p.board[m.from()]);
            const int exchange = options.see ? static_exchange(p, m) : value[victim] - value[attacker];
            return (exchange >= 0 ? 10000000 : -1000000)
                + 32 * value[victim] - value[attacker] + 8 * int(m.promotion()) + std::clamp(exchange, -20000, 20000);
        }
        if (ply < MaxPly && m == killers[ply][0]) return 900000;
        if (ply < MaxPly && m == killers[ply][1]) return 800000;
        return history[p.side][m.from()][m.to()];
    }
    struct Ordered {
        MoveList moves;
        std::array<int, 256> scores{};
        Ordered(Impl& search, const Position& p, MoveList list, Move hash, int ply) : moves(list) {
            for (int i = 0; i < moves.size(); ++i) scores[i] = search.move_score(p, moves[i], hash, ply);
        }
        Move next(int index) {
            int best = index;
            for (int j = index + 1; j < moves.size(); ++j) if (scores[j] > scores[best]) best = j;
            std::swap(scores[index], scores[best]); std::swap(moves[index], moves[best]); return moves[index];
        }
    };
    void update_pv(int ply, Move move) {
        pv[ply][0] = move;
        const int child_length = ply + 1 < MaxPly ? pv_length[ply + 1] : 0;
        const int copy = std::min(child_length, MaxPly - ply - 1);
        for (int i = 0; i < copy; ++i) pv[ply][i + 1] = pv[ply + 1][i];
        pv_length[ply] = copy + 1;
    }
    NodeValue quiescence(Position& p, int alpha, int beta, int ply, bool null_branch) {
        if (!visit(ply)) return {0};
        pv_length[ply] = 0;
        const bool check = p.in_check();
        NodeValue drawn{};
        if (draw(p, ply, null_branch, check, drawn)) return drawn;
        MoveList tactical;
        if (options.fast_quiescence && !check) {
            tactical = generate_moves(p, true);
            // A legal tactical move proves this is not stalemate. Otherwise
            // find just one quiet legal move before permitting stand pat.
            if (tactical.empty() && !has_legal(p)) return {0};
        } else {
            // The full generator remains a reference path and supplies every
            // evasion in check, including quiet king moves and interpositions.
            const MoveList legal = generate_moves(p);
            if (legal.empty()) return {check ? -MateScore + ply : 0};
            for (Move m : legal)
                if (check || m.capture() || m.promotion() != Empty) tactical.push(m);
        }
        NodeValue exact{};
        if (probe_outcome(p, ply, null_branch, exact)) return exact;
        if (ply >= MaxPly - 1) return {evaluate_position(p, ply)};
        int best = check ? -Infinity : evaluate_position(p, ply);
        if (!check) {
            if (best >= beta) return {best};
            alpha = std::max(alpha, best);
        }
        Ordered ordered(*this, p, tactical, Move{}, ply);
        bool path_draw = false;
        for (int i = 0; i < ordered.moves.size(); ++i) {
            Move m = ordered.next(i);
            Undo undo; p.make(m, undo);
            update_child_state(p, m, undo, ply, null_branch);
            const NodeValue child = quiescence(p, -beta, -alpha, ply + 1, null_branch);
            p.unmake(m, undo);
            if (aborted) return {0};
            path_draw |= child.contextual_draw;
            const int score = -child.score;
            best = std::max(best, score);
            if (score > alpha) { alpha = score; update_pv(ply, m); }
            if (alpha >= beta) break;
        }
        return {best, path_draw};
    }
    NodeValue negamax(Position& p, int depth, int alpha, int beta, int ply,
                      bool pv_node, bool null_branch, bool previous_null) {
        if (depth <= 0) return quiescence(p, alpha, beta, ply, null_branch);
        if (!visit(ply)) return {0};
        pv_length[ply] = 0;
        const bool check = p.in_check();
        NodeValue drawn{};
        if (draw(p, ply, null_branch, check, drawn)) return drawn;
        if (ply >= MaxPly - 1) {
            if (generate_moves(p).empty()) return {check ? -MateScore + ply : 0};
            return {evaluate_position(p, ply)};
        }
        alpha = std::max(alpha, -MateScore + ply);
        beta = std::min(beta, MateScore - ply - 1);
        if (alpha >= beta) return {alpha};
        if (check) ++depth;
        const int original_alpha = alpha;
        const std::uint64_t key = table_key(p, repetition_context[ply]);
        Move hash;
        if (!null_branch) {
            const Entry& e = table[key & mask];
            if (e.bound != NoBound && e.key == key) {
                hash = e.move;
                const int value = from_table(e.score, ply);
                if (e.depth >= depth && !pv_node && ply > 0
                    && (e.bound == Exact || (e.bound == Lower && value >= beta) || (e.bound == Upper && value <= alpha)))
                    return {value};
            }
            // A hint carries no value or bound. It only gives priority to a
            // matching member of the legal list; history-qualified scores above
            // remain the only table entries allowed to terminate a search.
            if (!hash && options.hash_move_hints) hash = move_hint(p.key);
        }
        const MoveList legal = ply == 0 ? [&] {
            MoveList moves; for (Move m : root_moves) moves.push(m); return moves;
        }() : generate_moves(p);
        if (legal.empty()) return {check ? -MateScore + ply : 0};
        NodeValue exact{};
        if (probe_outcome(p, ply, null_branch, exact)) return exact;
        // Ordinary alpha-beta nodes only consume the searched child scores.
        // Avoid recomputing the full evaluator when neither selective test uses it.
        const int static_eval = options.null_move || options.futility ? evaluate_position(p, ply) : 0;
        const bool has_nonpawn = (p.bb[p.side][Knight] | p.bb[p.side][Bishop] | p.bb[p.side][Rook] | p.bb[p.side][Queen]) != 0;
        // Selective options remain off until controlled matches demonstrate gains.
        if (options.null_move && !pv_node && !check && !previous_null && !null_branch && depth >= 3
            && static_eval >= beta && has_nonpawn && std::abs(beta) < MateThreshold && p.halfmove < 90) {
            Undo undo; p.make_null(undo);
            repetition_context[ply + 1] = repetition_context[ply];
            if (network) accumulators[ply + 1] = accumulators[ply];
            const int reduction = 2 + depth / 5;
            const NodeValue child = negamax(p, depth - reduction - 1, -beta, -beta + 1, ply + 1, false, true, true);
            p.unmake_null(undo);
            if (aborted) return {0};
            if (-child.score >= beta && std::abs(child.score) < MateThreshold) return {-child.score};
        }
        Ordered ordered(*this, p, legal, hash, ply);
        int best = -Infinity, searched = 0;
        Move best_move;
        bool path_draw = false;
        std::array<Move, 256> quiets{}; int quiet_count = 0;
        for (int i = 0; i < ordered.moves.size(); ++i) {
            const Move m = ordered.next(i);
            const bool quiet = !m.capture() && m.promotion() == Empty;
            Undo undo; p.make(m, undo);
            update_child_state(p, m, undo, ply, null_branch);
            const bool gives_check = p.in_check();
            // If every searched move loses by mate, another quiet move may be
            // the escape. A static futility estimate cannot prove it also mates.
            if (options.futility && searched > 0 && !pv_node && !check && quiet && !gives_check
                && best > -MateThreshold && depth <= 2
                && static_eval + 130 * depth <= alpha && std::abs(alpha) < MateThreshold) {
                p.unmake(m, undo); continue;
            }
            const int child_depth = depth - 1;
            NodeValue child{};
            int reduction = 0;
            if (options.lmr && searched >= 3 && depth >= 3 && quiet && !check && !gives_check && !pv_node) {
                reduction = 1 + (depth >= 6 && searched >= 8 ? 1 : 0);
                reduction = std::min(reduction, child_depth - 1);
            }
            if (searched == 0 || !options.pvs) {
                child = negamax(p, child_depth, -beta, -alpha, ply + 1, pv_node, null_branch, false);
            } else {
                child = negamax(p, child_depth - reduction, -alpha - 1, -alpha, ply + 1, false, null_branch, false);
                path_draw |= child.contextual_draw;
                if (!aborted && reduction && -child.score > alpha)
                    child = negamax(p, child_depth, -alpha - 1, -alpha, ply + 1, false, null_branch, false);
                path_draw |= child.contextual_draw;
                if (!aborted && -child.score > alpha && -child.score < beta)
                    child = negamax(p, child_depth, -beta, -alpha, ply + 1, pv_node, null_branch, false);
            }
            p.unmake(m, undo);
            if (aborted) return {0};
            ++searched; path_draw |= child.contextual_draw;
            const int score = -child.score;
            if (score > best) { best = score; best_move = m; }
            if (score > alpha) { alpha = score; update_pv(ply, m); }
            if (alpha >= beta) {
                if (quiet) {
                    if (killers[ply][0] != m) { killers[ply][1] = killers[ply][0]; killers[ply][0] = m; }
                    const int bonus = std::min(2000, depth * depth * 16);
                    auto& h = history[p.side][m.from()][m.to()]; h += bonus - h * bonus / 16384;
                    for (int q = 0; q < quiet_count; ++q) {
                        auto& bad = history[p.side][quiets[q].from()][quiets[q].to()];
                        bad -= bonus + bad * bonus / 16384;
                    }
                }
                break;
            }
            if (quiet) quiets[quiet_count++] = m;
        }
        // A restricted root searches only a subset of legal moves. Its score
        // cannot be reused under the unrestricted position key at another ply.
        const bool restricted_root = ply == 0 && !limits.searchmoves.empty();
        if (!null_branch && !path_draw && !restricted_root)
            save(key, depth, best, best >= beta ? Lower : best <= original_alpha ? Upper : Exact, best_move, ply);
        if (options.hash_move_hints && !null_branch && !restricted_root && best_move)
            save_hint(p.key, depth, best_move);
        return {best, path_draw};
    }

    bool root_tablebase(Position& p, [[maybe_unused]] const MoveList& complete_legal, SearchResult& result,
                        const std::function<void(const SearchInfo&)>& callback) {
        if (!tablebase_eligible(p)) return false;
        const bool history_sensitive = repeated_history(p);
        const auto cancelled = [&] {
            return stop->load(std::memory_order_relaxed) || (hard_ms && elapsed() >= hard_ms);
        };
        if (cancelled()) return false;
#if ORIENT_REUSE_ROOT_LEGAL
        const auto probe = tablebases->probe_root(p, complete_legal, cancelled);
#else
        const auto probe = tablebases->probe_root(p, cancelled);
#endif
        if (probe.status != ProbeStatus::Success || cancelled()) return false;
        // Earlier repetitions add draw opportunities. They cannot turn a
        // board/clock draw into a forced loss, so a drawing root may retain a
        // certified drawing move. Decisive and cursed/blessed results remain
        // with ordinary history-aware search: a losing label may be rescued by
        // repetition, and a winning label need not still be an exact win.
        if (history_sensitive && probe.wdl != 2) return false;
        ++tablebase_hits;
        Move best;
        int best_score = -Infinity;
        unsigned best_dtz = 0;
#if ORIENT_TABLEBASE_PROFILING
        struct AdjudicationTimer {
            SearchResult& result;
            Clock::time_point start;
            ~AdjudicationTimer() {
                result.profile_root_adjudication_ns += std::uint64_t(
                    std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count());
            }
        } timer{result, Clock::now()};
#endif
        for (Move move : root_moves) {
            const auto found = std::find_if(probe.moves.begin(), probe.moves.end(),
                [&](const TablebaseMove& item) { return item.move == move; });
            if (found == probe.moves.end()) return false;
            int score = tablebase_score(found->wdl);
            // Resolve actual terminal and history-dependent draws with Orient's
            // own rules before trusting a board-only table result.
            Undo undo; p.make(move, undo);
            NodeValue child_draw{};
            const bool check = p.in_check();
            bool actual_draw = false;
            if (check && !has_legal(p)) score = MateScore - 1;
            else if (draw(p, 1, false, check, child_draw)) {
                score = -child_draw.score;
                actual_draw = score == 0;
            }
            // Original Syzygy DTZ may be rounded by one ply. A quiet move
            // exactly on the rule-50 boundary needs ordinary search instead.
            const bool ambiguous = p.halfmove != 0 && score != MateScore - 1
                && found->dtz != 0 && found->dtz + unsigned(undo.halfmove) == 100;
            p.unmake(move, undo);
            if (ambiguous) return false;
            // Never declare a quiet losing-labelled move an exact loss using
            // history-free data. If no permitted drawing alternative is
            // certified, return to the unchanged history-aware search. An
            // actual immediate draw is also safe even when its table label
            // loses; the complete game history above decides that case.
            if (history_sensitive && (score != 0 || (found->wdl != 2 && !actual_draw))) continue;
            bool better = !best || score > best_score;
            if (score == best_score) {
                if (score > 0) better = found->dtz < best_dtz;
                else if (score < 0) better = found->dtz > best_dtz;
                if (found->dtz == best_dtz && move == probe.suggested) better = true;
            }
            if (better) { best = move; best_score = score; best_dtz = found->dtz; }
        }
        if (!best || cancelled()) return false;
        result.best = best; result.pv = {best}; result.score = best_score;
        result.depth = 0; result.nodes = nodes; result.tablebase_hits = tablebase_hits;
        if (callback) callback(SearchInfo{0, 0, result.score, nodes, elapsed(), result.pv, tablebase_hits});
        return true;
    }

    SearchResult run(Position p, const SearchLimits& requested, std::atomic_bool& requested_stop,
                     const std::function<void(const SearchInfo&)>& callback) {
        limits = requested; stop = &requested_stop;
        const auto now = Clock::now();
        start = requested.received_at == Clock::time_point{} ? now : std::min(now, requested.received_at);
        aborted = false; nodes = 0; seldepth = 0; tablebase_hits = 0; ++generation;
        pv_length.fill(0); killers = {};
        for (auto& side : history) for (auto& from : side) for (int& score : from) score /= 2;
        budget(p.side);
#if ORIENT_TABLEBASE_PROFILING
        const auto legal_start = Clock::now();
#endif
        const MoveList legal = generate_moves(p);
        SearchResult result;
#if ORIENT_TABLEBASE_PROFILING
        result.profile_root_legal_ns = std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
            Clock::now() - legal_start).count());
#endif
        if (legal.empty()) { result.score = p.in_check() ? -MateScore : 0; return result; }
        root_moves.clear();
        for (Move m : legal) {
            if (limits.searchmoves.empty() || std::find(limits.searchmoves.begin(), limits.searchmoves.end(), m) != limits.searchmoves.end())
                root_moves.push_back(m);
        }
        if (root_moves.empty()) return result;
        if (network) accumulators[0] = network->rebuild(p);
        repetition_context[0] = history_context(p);
        result.best = root_moves.front(); result.pv = {result.best}; result.score = evaluate_position(p, 0);
        NodeValue drawn{};
        if (draw(p, 0, false, p.in_check(), drawn)) { result.score = drawn.score; return result; }
        if (root_tablebase(p, legal, result, callback)) return result;
        const int maximum_depth = std::clamp(limits.depth, 1, MaxPly - 2);
        for (int depth = 1; depth <= maximum_depth; ++depth) {
            int window = 28;
            int alpha = -Infinity, beta = Infinity;
            if (options.aspiration && depth >= 4 && std::abs(result.score) < MateThreshold) {
                alpha = std::max(-Infinity, result.score - window); beta = std::min(Infinity, result.score + window);
            }
            NodeValue value{};
            for (;;) {
                value = negamax(p, depth, alpha, beta, 0, true, false, false);
                if (aborted) break;
                if (value.score <= alpha && alpha > -Infinity) {
                    window = std::min(Infinity, window * 2); alpha = std::max(-Infinity, value.score - window);
                } else if (value.score >= beta && beta < Infinity) {
                    window = std::min(Infinity, window * 2); beta = std::min(Infinity, value.score + window);
                } else break;
            }
            if (aborted) break;
            result.depth = depth; result.score = value.score;
            if (pv_length[0]) { result.pv.assign(pv[0].begin(), pv[0].begin() + pv_length[0]); result.best = result.pv.front(); }
            result.nodes = nodes;
            result.tablebase_hits = tablebase_hits;
            if (callback) callback(SearchInfo{depth, seldepth, value.score, nodes, elapsed(), result.pv, tablebase_hits});
            if ((soft_ms && elapsed() >= soft_ms) || stop->load(std::memory_order_relaxed)) break;
            if (std::abs(result.score) >= MateThreshold && MateScore - std::abs(result.score) <= depth) break;
        }
        result.nodes = nodes; result.tablebase_hits = tablebase_hits; return result;
    }
};

Searcher::Searcher(std::size_t hash_mb) : impl_(std::make_unique<Impl>(hash_mb)) {}
Searcher::~Searcher() = default;
void Searcher::resize_hash(std::size_t hash_mb) { impl_->resize(hash_mb); }
void Searcher::clear() {
    std::fill(impl_->table.begin(), impl_->table.end(), Impl::Entry{});
    std::fill(impl_->hints.begin(), impl_->hints.end(), Impl::HintEntry{});
    impl_->history = {}; impl_->killers = {};
}
void Searcher::set_options(SearchOptions options) { impl_->options = options; }
SearchOptions Searcher::options() const { return impl_->options; }
void Searcher::set_network(std::shared_ptr<const NeuralNetwork> network) {
    impl_->network = std::move(network);
    clear();
}
void Searcher::set_tablebases(std::shared_ptr<Tablebases> tables, int probe_limit) {
    if (probe_limit < 0 || probe_limit > 5) throw std::invalid_argument("SyzygyProbeLimit must be 0..5");
    impl_->tablebases = std::move(tables);
    impl_->tablebase_limit = probe_limit;
    clear();
}
SearchResult Searcher::search(Position position, const SearchLimits& limits, std::atomic_bool& stop,
                              std::function<void(const SearchInfo&)> on_info) {
    return impl_->run(std::move(position), limits, stop, on_info);
}
} // namespace orient
