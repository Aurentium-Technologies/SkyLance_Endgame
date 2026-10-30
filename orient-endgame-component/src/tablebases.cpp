#include "orient/tablebases.hpp"
#include "orient/detail/tablebase_cache.hpp"
#include <tbprobe.h>

#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <filesystem>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <utility>

namespace orient {
namespace {
struct Reader {
    std::mutex mutex;
    std::string path;
    std::uint64_t generation = 0;
    unsigned largest = 0;
    bool initialized = false;
    ~Reader() { if (initialized) tb_free(); }
    void activate(const std::string& next, bool force = false) {
        if (!force && initialized && path == next) return;
        if (initialized) tb_free();
        path = next;
        largest = 0;
        initialized = true;
        ++generation;
        // Fathom considers an empty directory a successful initialization;
        // TB_LARGEST, not just tb_init's return, determines availability.
        if (!next.empty() && tb_init(next.c_str())) largest = std::min(5u, TB_LARGEST);
    }
};
Reader& reader() { static Reader value; return value; }

struct Board {
    std::array<std::uint64_t, 8> bits{};
    unsigned ep = 0;
    bool turn = true;
    bool operator==(const Board&) const = default;
};
Board board_of(const Position& p) {
    return {{p.occupied[White], p.occupied[Black],
             p.bb[White][King] | p.bb[Black][King],
             p.bb[White][Queen] | p.bb[Black][Queen],
             p.bb[White][Rook] | p.bb[Black][Rook],
             p.bb[White][Bishop] | p.bb[Black][Bishop],
             p.bb[White][Knight] | p.bb[Black][Knight],
             p.bb[White][Pawn] | p.bb[Black][Pawn]},
            p.ep < 0 ? 0u : unsigned(p.ep), p.side == White};
}
bool eligible(const Position& p) {
    return p.castling == 0 && std::popcount(p.occupancy()) <= 5;
}
unsigned raw_wdl(const Board& b) {
    return tb_probe_wdl(b.bits[0], b.bits[1], b.bits[2], b.bits[3],
                        b.bits[4], b.bits[5], b.bits[6], b.bits[7],
                        0, 0, b.ep, b.turn);
}
unsigned raw_root(const Board& b, unsigned halfmove, unsigned* alternatives) {
    return tb_probe_root(b.bits[0], b.bits[1], b.bits[2], b.bits[3],
                         b.bits[4], b.bits[5], b.bits[6], b.bits[7],
                         halfmove, 0, b.ep, b.turn, alternatives);
}
PieceType promotion_of(unsigned encoded) {
    switch (TB_GET_PROMOTES(encoded)) {
    case TB_PROMOTES_NONE: return Empty;
    case TB_PROMOTES_QUEEN: return Queen;
    case TB_PROMOTES_ROOK: return Rook;
    case TB_PROMOTES_BISHOP: return Bishop;
    case TB_PROMOTES_KNIGHT: return Knight;
    default: return King; // No legal promotion can match this sentinel.
    }
}
Move own_move(unsigned encoded, const MoveList& legal) {
    const int from = int(TB_GET_FROM(encoded)), to = int(TB_GET_TO(encoded));
    const PieceType promotion = promotion_of(encoded);
    const bool ep = TB_GET_EP(encoded) != 0;
    for (Move move : legal)
        if (move.from() == from && move.to() == to && move.promotion() == promotion
            && move.has(Move::EnPassant) == ep) return move;
    return {};
}
std::string normalized_path(std::string path) {
    if (path.empty() || path == "<empty>") return {};
    // A single directory keeps configuration portable and prevents a path-list
    // delimiter from being interpreted differently across operating systems.
#ifdef _WIN32
    constexpr char separator = ';';
#else
    constexpr char separator = ':';
#endif
    if (path.find(separator) != std::string::npos)
        throw std::invalid_argument("SyzygyPath must name one directory");
    std::error_code error;
    const auto canonical = std::filesystem::weakly_canonical(path, error);
    return error ? std::move(path) : canonical.string();
}
}

struct Tablebases::Impl {
#if ORIENT_COMPACT_TABLEBASE_CACHE
    using Entry = detail::PackedTablebaseEntry;
#else
    struct Entry {
        Board board;
        std::uint8_t wdl = 2;
        bool valid = false;
    };
#endif
    std::string path;
    std::unique_ptr<Entry[]> cache;
    std::size_t count = 0;
    std::uint64_t generation = 0;
    unsigned largest = 0;
    TablebaseStats stats;
    Impl(std::string next, std::size_t mib) : path(normalized_path(std::move(next))) {
        if (mib > 256) throw std::invalid_argument("SyzygyCache must be between 0 and 256 MiB");
        const std::size_t bytes = mib * 1024 * 1024;
        count = bytes / sizeof(Entry);
        if (count) cache = std::make_unique<Entry[]>(count);
        auto& backend = reader();
        std::lock_guard guard(backend.mutex);
        backend.activate(path, true);
        synchronize(backend);
    }
    void synchronize(Reader& backend) {
        backend.activate(path);
        if (generation != backend.generation) {
            clear();
            generation = backend.generation;
        }
        largest = backend.largest;
    }
    void clear() {
        // Reinitializing avoids retaining successful values across dataset
        // changes, without allocating a second full-size cache temporarily.
#if ORIENT_COMPACT_TABLEBASE_CACHE
        std::fill_n(cache.get(), count, Entry{});
#else
        for (std::size_t i = 0; i < count; ++i) cache[i].valid = false;
#endif
    }
};

Tablebases::Tablebases(std::string path, std::size_t cache_mib)
    : impl_(std::make_unique<Impl>(std::move(path), cache_mib)) {}
Tablebases::~Tablebases() = default;

WdlProbe Tablebases::probe_wdl(const Position& p) {
    if (!eligible(p) || p.halfmove != 0) return {ProbeStatus::Unsupported, 2};
    auto& backend = reader();
    std::lock_guard guard(backend.mutex);
    auto& state = *impl_;
    state.synchronize(backend);
    ++state.stats.probes;
    if (std::popcount(p.occupancy()) > int(state.largest)) return {};
    // Zobrist keys only select a slot; full board equality verifies identity.
    auto* entry = state.count ? &state.cache[p.key % state.count] : nullptr;
#if ORIENT_COMPACT_TABLEBASE_CACHE
    std::optional<std::uint64_t> identity;
    if (entry) {
        identity = detail::pack_tablebase_identity(p);
        if (!identity) return {ProbeStatus::Unsupported, 2};
        if (detail::tablebase_entry_matches(*entry, *identity)) {
            ++state.stats.hits; ++state.stats.cache_hits;
            return {ProbeStatus::Success, detail::tablebase_entry_wdl(*entry)};
        }
    }
    const auto board = board_of(p);
#else
    const auto board = board_of(p);
    if (entry && entry->valid && entry->board == board) {
        ++state.stats.hits; ++state.stats.cache_hits;
        return {ProbeStatus::Success, int(entry->wdl)};
    }
#endif
    const unsigned value = raw_wdl(board);
    if (value == TB_RESULT_FAILED || value > TB_WIN) return {};
    if (entry) {
#if ORIENT_COMPACT_TABLEBASE_CACHE
        *entry = detail::make_tablebase_entry(*identity, int(value));
#else
        *entry = Impl::Entry{board, std::uint8_t(value), true};
#endif
    }
    ++state.stats.hits;
    return {ProbeStatus::Success, int(value)};
}

RootProbe Tablebases::probe_root(const Position& p, const std::function<bool()>& cancelled) {
    if (!eligible(p) || p.halfmove < 0 || p.halfmove >= 100)
        return {ProbeStatus::Unsupported, 2, 0, {}, {}};
    if (cancelled && cancelled()) return {};
    // The engine's own rules determine terminal states and every returned move.
#if ORIENT_TABLEBASE_PROFILING
    const auto started = std::chrono::steady_clock::now();
#endif
    Position own = p;
    const MoveList legal = own.legal_moves();
#if ORIENT_TABLEBASE_PROFILING
    const auto duration = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now() - started).count();
    {
        auto& backend = reader(); std::lock_guard guard(backend.mutex);
        impl_->stats.root_legal_ns += std::uint64_t(duration);
    }
#endif
    return probe_root(p, legal, cancelled);
}

RootProbe Tablebases::probe_root(const Position& p, const MoveList& legal,
                                const std::function<bool()>& cancelled) {
    if (!eligible(p) || p.halfmove < 0 || p.halfmove >= 100)
        return {ProbeStatus::Unsupported, 2, 0, {}, {}};
    if (cancelled && cancelled()) return {};
    if (legal.empty()) {
        // Even an empty supplied list may not manufacture a terminal result.
        Position own = p;
        if (own.has_legal_move()) return {};
        return {ProbeStatus::Success, own.in_check() ? 0 : 2, 0, {}, {}};
    }
    auto& backend = reader();
    std::lock_guard guard(backend.mutex);
    auto& state = *impl_;
    state.synchronize(backend);
    ++state.stats.probes;
    if (std::popcount(p.occupancy()) > int(state.largest)) return {};
    const auto board = board_of(p);
    std::array<unsigned, TB_MAX_MOVES> alternatives;
    alternatives.fill(TB_RESULT_FAILED);
#if ORIENT_TABLEBASE_PROFILING
    const auto probe_start = std::chrono::steady_clock::now();
    ++state.stats.root_calls;
#endif
    const unsigned value = raw_root(board, unsigned(p.halfmove), alternatives.data());
#if ORIENT_TABLEBASE_PROFILING
    state.stats.root_probe_ns += std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now() - probe_start).count());
    const auto validation_start = std::chrono::steady_clock::now();
    struct ValidationTimer {
        TablebaseStats& stats;
        std::chrono::steady_clock::time_point start;
        ~ValidationTimer() {
            stats.root_validation_ns += std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now() - start).count());
        }
    } timer{state.stats, validation_start};
#endif
    if ((cancelled && cancelled()) || value == TB_RESULT_FAILED) return {};
    const Move suggested = own_move(value, legal);
    if (!suggested) return {}; // Sentinel or disagreement with our legal moves.
    RootProbe result{ProbeStatus::Success, int(TB_GET_WDL(value)),
                     TB_GET_DTZ(value), suggested, {}};
    if (result.wdl > int(TB_WIN)) return {};
#if ORIENT_REUSE_ROOT_LEGAL
    result.moves.reserve(std::size_t(legal.size()));
#if ORIENT_TABLEBASE_PROFILING
    ++state.stats.root_allocations;
#endif
#endif
    for (const unsigned encoded : alternatives) {
        if (encoded == TB_RESULT_FAILED) break;
        const Move move = own_move(encoded, legal);
        if (!move || TB_GET_WDL(encoded) > TB_WIN) return {};
        if (std::any_of(result.moves.begin(), result.moves.end(),
                        [move](const auto& found) { return found.move == move; })) return {};
#if ORIENT_TABLEBASE_PROFILING
        if (result.moves.size() == result.moves.capacity()) ++state.stats.root_allocations;
#endif
        result.moves.push_back({move, int(TB_GET_WDL(encoded)), TB_GET_DTZ(encoded)});
    }
    // No partial result may hide an unprobed alternative, even if its suggested
    // move happens to be legal. A caller can safely apply searchmoves afterwards.
    if (result.moves.size() != std::size_t(legal.size())) return {};
    if (std::none_of(result.moves.begin(), result.moves.end(),
                     [suggested](const auto& move) { return move.move == suggested; })) return {};
    ++state.stats.hits;
    return result;
}

void Tablebases::clear_cache() {
    auto& backend = reader(); std::lock_guard guard(backend.mutex);
    impl_->clear();
}
std::size_t Tablebases::cache_bytes() const { return impl_->count * sizeof(Impl::Entry); }
std::size_t Tablebases::cache_entry_bytes() const { return sizeof(Impl::Entry); }
std::size_t Tablebases::cache_capacity() const { return impl_->count; }
unsigned Tablebases::largest() const {
    auto& backend = reader(); std::lock_guard guard(backend.mutex);
    impl_->synchronize(backend);
    return impl_->largest;
}
TablebaseStats Tablebases::stats() const {
    auto& backend = reader(); std::lock_guard guard(backend.mutex);
    return impl_->stats;
}
} // namespace orient
