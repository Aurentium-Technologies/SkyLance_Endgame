#pragma once

#include "orient/chess.hpp"
#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <vector>

namespace orient {
class NeuralNetwork;
class Tablebases;
inline constexpr int MateScore = 30000;
inline constexpr int TablebaseScore = 25000;
inline constexpr int MaxPly = 128;

struct SearchLimits {
    int depth = 64;
    std::uint64_t nodes = 0;
    std::int64_t movetime_ms = 0, wtime_ms = 0, btime_ms = 0;
    std::int64_t winc_ms = 0, binc_ms = 0;
    int movestogo = 0, overhead_ms = 50;
    // UCI supplies its request/setup start; direct callers may leave this empty.
    std::chrono::steady_clock::time_point received_at{};
    bool infinite = false;
    std::vector<Move> searchmoves;
};
struct SearchOptions {
    bool pvs = true, aspiration = true, see = true;
    bool null_move = false, lmr = false, futility = false;
    bool fast_quiescence = false;
    bool hash_move_hints = false;
    bool direct_legal = false;
};
struct SearchInfo {
    int depth = 0, seldepth = 0, score = 0;
    std::uint64_t nodes = 0;
    std::int64_t elapsed_ms = 0;
    std::vector<Move> pv;
    std::uint64_t tablebase_hits = 0;
};
struct SearchResult {
    Move best;
    int score = 0, depth = 0;
    std::uint64_t nodes = 0;
    std::vector<Move> pv;
    std::uint64_t tablebase_hits = 0;
    // Optional application profiling; zero in acceptance/production builds.
    std::uint64_t profile_root_legal_ns = 0, profile_root_adjudication_ns = 0;
};
int evaluate(const Position& position);
int static_exchange(const Position& position, Move move);

class Searcher {
public:
    explicit Searcher(std::size_t hash_mb = 256);
    ~Searcher();
    Searcher(const Searcher&) = delete;
    Searcher& operator=(const Searcher&) = delete;
    void resize_hash(std::size_t hash_mb);
    void clear();
    void set_options(SearchOptions options);
    SearchOptions options() const;
    void set_network(std::shared_ptr<const NeuralNetwork> network);
    void set_tablebases(std::shared_ptr<Tablebases> tables, int probe_limit = 5);
    SearchResult search(Position position, const SearchLimits& limits,
                        std::atomic_bool& stop,
                        std::function<void(const SearchInfo&)> on_info = {});
private:
    friend struct SearchTestAccess;
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace orient
