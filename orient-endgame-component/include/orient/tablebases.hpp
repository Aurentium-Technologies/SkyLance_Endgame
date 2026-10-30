#pragma once

#include "orient/chess.hpp"
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace orient {
enum class ProbeStatus { Success, Unsupported, Unavailable };
struct WdlProbe {
    ProbeStatus status = ProbeStatus::Unavailable;
    // Syzygy's five outcomes, from the side-to-move's perspective:
    // 0 loss, 1 loss drawn by the 50-move rule, 2 draw, 3 win drawn by that
    // rule, 4 win. These values are not engine evaluation scores.
    int wdl = 2;
};
struct TablebaseMove {
    Move move;
    int wdl = 2;
    unsigned dtz = 0;
};
struct RootProbe {
    ProbeStatus status = ProbeStatus::Unavailable;
    int wdl = 2;
    unsigned dtz = 0;
    Move suggested;
    std::vector<TablebaseMove> moves;
};
struct TablebaseStats {
    std::uint64_t probes = 0, hits = 0, cache_hits = 0;
    // Populated only by an opt-in profiling build; production timing is clean.
    std::uint64_t root_calls = 0, root_legal_ns = 0, root_probe_ns = 0;
    std::uint64_t root_validation_ns = 0, root_allocations = 0;
};

// Own adapter around the separately attributed Fathom reader. Files are
// immutable while a provider is in use. The raw-WDL cache contains no search
// scores, game histories or draw decisions. This class serializes access to
// Fathom's process-global state, including changes between providers.
class Tablebases {
public:
    explicit Tablebases(std::string path, std::size_t cache_mib = 0);
    ~Tablebases();
    Tablebases(const Tablebases&) = delete;
    Tablebases& operator=(const Tablebases&) = delete;
    WdlProbe probe_wdl(const Position& position);
    RootProbe probe_root(const Position& position,
                         const std::function<bool()>& cancelled = {});
    // complete_legal must be the full validated list for position, before any
    // searchmoves restriction. The adapter still verifies every reader move.
    RootProbe probe_root(const Position& position, const MoveList& complete_legal,
                         const std::function<bool()>& cancelled = {});
    void clear_cache();
    std::size_t cache_bytes() const;
    std::size_t cache_entry_bytes() const;
    std::size_t cache_capacity() const;
    unsigned largest() const;
    TablebaseStats stats() const;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace orient
