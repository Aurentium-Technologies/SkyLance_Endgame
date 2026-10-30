#include "orient/tablebases.hpp"
#include <algorithm>
#include <bit>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace orient;
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
Position position(const char* fen) {
    Position result; std::string error;
    if (!result.set_fen(fen, &error)) throw std::runtime_error(error);
    return result;
}
void same_root(const RootProbe& a, const RootProbe& b) {
    check(a.status == b.status && a.wdl == b.wdl && a.dtz == b.dtz && a.suggested == b.suggested,
          "Root overload changed status, outcome, DTZ or suggested move");
    check(a.moves.size() == b.moves.size(), "Root overload changed alternative count");
    for (std::size_t i = 0; i < a.moves.size(); ++i)
        check(a.moves[i].move == b.moves[i].move && a.moves[i].wdl == b.moves[i].wdl
              && a.moves[i].dtz == b.moves[i].dtz, "Root overload changed ordered alternatives");
}
struct TemporaryDirectory {
    std::filesystem::path path = std::filesystem::temp_directory_path()
        / ("orient-tablebase-test-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    TemporaryDirectory() { check(std::filesystem::create_directory(path), "Cannot create test directory"); }
    ~TemporaryDirectory() { std::error_code ignored; std::filesystem::remove_all(path, ignored); }
};
int main(int argc, char** argv) {
    try {
        const auto queen = position("6k1/8/8/8/8/8/8/K2Q4 w - - 0 1");
        for (std::size_t mib : {0u, 1u, 3u, 4u, 16u}) {
            Tablebases sized("/definitely-not-an-orient-tablebase-directory", mib);
#if ORIENT_COMPACT_TABLEBASE_CACHE
            check(sized.cache_entry_bytes() == 8, "Compact cache entry is not eight bytes");
#endif
            check(sized.cache_entry_bytes() > 0, "Cache entry size unavailable");
            check(sized.cache_capacity() == mib * 1024 * 1024 / sized.cache_entry_bytes(),
                  "Cache capacity differs from exact advertised budget");
            check(sized.cache_bytes() == sized.cache_capacity() * sized.cache_entry_bytes()
                  && sized.cache_bytes() <= mib * 1024 * 1024,
                  "Cache allocation exceeds capacity or advertised budget");
#if ORIENT_COMPACT_TABLEBASE_CACHE
            if (mib == 3) check(!std::has_single_bit(sized.cache_capacity()),
                                "Three-MiB regression fixture must have non-power-of-two capacity");
#endif
        }
        Tablebases missing("/definitely-not-an-orient-tablebase-directory", 4);
        check(missing.largest() == 0, "Missing directory must report unavailable");
        check(missing.probe_wdl(queen).status == ProbeStatus::Unavailable, "Missing WDL must not become draw");
        check(missing.probe_root(queen).status == ProbeStatus::Unavailable, "Missing root must not become draw");
        auto queen_copy = queen;
        const auto queen_legal = queen_copy.legal_moves();
        check(missing.probe_root(queen, queen_legal).status == ProbeStatus::Unavailable,
              "Reused legal list bypassed unavailable provider");
        check(missing.probe_wdl(queen).status == ProbeStatus::Unavailable,
              "Repeated failed WDL must remain unavailable");
        check(missing.probe_wdl(Position{}).status == ProbeStatus::Unsupported, "Start position is unsupported");
        auto clock = queen; clock.halfmove = 1;
        check(missing.probe_wdl(clock).status == ProbeStatus::Unsupported, "Nonzero clock cannot use raw WDL");
        const auto castle = position("4k3/8/8/8/8/8/8/4K2R w K - 0 1");
        check(missing.probe_root(castle).status == ProbeStatus::Unsupported, "Castling is unsupported");
        check(missing.probe_root(queen, [] { return true; }).status == ProbeStatus::Unavailable,
              "Cancelled probe cannot supply a result");
        check(missing.stats().cache_hits == 0, "Failed probes must not be cached");
        check(missing.cache_bytes() <= 4 * 1024 * 1024, "Cache exceeds declared bound");
        missing.clear_cache();
        bool rejected = false;
        try { Tablebases too_large("", 257); } catch (const std::invalid_argument&) { rejected = true; }
        check(rejected, "Invalid cache setting accepted");
        rejected = false;
#ifdef _WIN32
        const char* path_list = "one;two";
#else
        const char* path_list = "one:two";
#endif
        try { Tablebases unsupported_paths(path_list); } catch (const std::invalid_argument&) { rejected = true; }
        check(rejected, "Ambiguous path list accepted as one dataset");
        {
            TemporaryDirectory directory;
            std::ofstream(directory.path / "KQvK.rtbw", std::ios::binary) << "bad";
            Tablebases truncated(directory.path.string());
            check(truncated.probe_wdl(queen).status == ProbeStatus::Unavailable,
                  "Truncated table cannot supply an outcome");
            // A correctly aligned file with a bad magic must also fail probing
            // safely. Installation checksums protect against deeper corruption.
            std::ofstream(directory.path / "KQvK.rtbw", std::ios::binary)
                << std::string(80, 'x');
            Tablebases bad_magic(directory.path.string(), 4);
            check(bad_magic.probe_wdl(queen).status == ProbeStatus::Unavailable,
                  "Corrupt magic cannot supply an outcome");
            check(bad_magic.probe_root(queen).status == ProbeStatus::Unavailable,
                  "Corrupt magic cannot supply a root move");
            check(bad_magic.stats().cache_hits == 0, "Corrupt probe failure entered cache");
        }
        std::cout << "Unavailable, unsupported, cancellation and bounded cache checks passed\n";
        const char* dataset = argc > 1 ? argv[1] : std::getenv("ORIENT_SYZYGY_PATH");
        if (!dataset || !*dataset) return 0;
        Tablebases tables(dataset, 4);
        check(tables.largest() == 5, "Complete five-piece collection required");
        for (std::size_t mib : {1u, 3u, 4u, 16u}) {
            Tablebases sized(dataset, mib);
            check(sized.probe_wdl(queen).status == ProbeStatus::Success,
                  "Permitted cache size cannot probe a valid position");
            check(sized.probe_wdl(queen).wdl == 4 && sized.stats().cache_hits == 1,
                  "Permitted cache size did not retain a successful raw result");
        }
#if ORIENT_COMPACT_TABLEBASE_CACHE
        {
            Tablebases non_power_of_two(dataset, 3);
            auto a = queen;
            auto b = position("6k1/8/8/8/8/8/8/K2R4 b - - 0 1");
            a.key = 0;
            b.key = non_power_of_two.cache_capacity() / 3;
            // At 393216 entries these keys occupy separate modulo slots, but
            // an incorrect count-1 bit mask maps both to zero.
            check((b.key & (non_power_of_two.cache_capacity() - 1)) == 0,
                  "Non-power-of-two indexing fixture no longer exercises the mask error");
            check(non_power_of_two.probe_wdl(a).wdl == 4 && non_power_of_two.probe_wdl(b).wdl == 0,
                  "Non-power-of-two cache changed a result");
            const auto hits = non_power_of_two.stats().cache_hits;
            check(non_power_of_two.probe_wdl(a).wdl == 4
                  && non_power_of_two.stats().cache_hits == hits + 1,
                  "Cache indexing incorrectly assumes a power-of-two capacity");
        }
#endif
        check(tables.probe_wdl(queen).wdl == 4, "KQvK must win");
        check(tables.probe_wdl(queen).status == ProbeStatus::Success, "Valid WDL unavailable");
        check(tables.stats().cache_hits == 1, "Repeated raw WDL did not hit cache");
        const auto before = tables.stats().cache_hits;
        auto collision = position("6k1/8/8/8/8/8/8/K2R4 b - - 0 1");
        collision.key = queen.key; // Deliberate slot collision; full board must still be verified.
        const auto different = tables.probe_wdl(collision);
        check(different.status == ProbeStatus::Success && different.wdl == 0, "Cache key collision changed outcome");
        check(tables.stats().cache_hits == before, "Cache accepted Zobrist collision as identity");
        tables.clear_cache();
        const auto cleared = tables.stats().cache_hits;
        check(tables.probe_wdl(queen).wdl == 4 && tables.stats().cache_hits == cleared,
              "Clear cache retained an entry");
        for (const char* fen : {
             "6k1/8/8/8/8/8/8/K2Q4 w - - 0 1",
             "6k1/8/8/8/8/8/8/K2Q4 b - - 0 1",
             "7k/P7/8/8/8/8/8/7K w - - 0 1",
             "8/1P6/k7/8/1K6/8/8/8 w - - 0 1",
             "8/8/8/3pP3/8/8/8/K6k w - d6 0 1",
             "4k3/8/8/8/3Pp3/8/8/4K3 b - d3 0 1",
             "8/8/8/8/8/2N5/2B5/K6k w - - 0 1",
             "4k3/8/8/8/8/8/8/R3K3 w - - 99 51"}) {
            auto p = position(fen);
            const auto original_fen = p.fen(); const auto original_key = p.key;
            if (p.halfmove == 0) {
                tables.clear_cache();
                const auto first = tables.probe_wdl(p);
                check(first.status == ProbeStatus::Success, "Special-case raw WDL unavailable");
                const auto hits = tables.stats().cache_hits;
                const auto second = tables.probe_wdl(p);
                check(second.status == ProbeStatus::Success && second.wdl == first.wdl
                      && tables.stats().cache_hits == hits + 1,
                      "Special-case position did not survive the raw-WDL cache");
            }
            const auto root = tables.probe_root(p);
            check(root.status == ProbeStatus::Success, "Required special-case root probe failed");
            check(p.fen() == original_fen && p.key == original_key && p.consistent(), "Probe changed position");
            check(root.moves.size() == std::size_t(p.legal_moves().size()), "Root move set incomplete");
            const auto legal = p.legal_moves();
            same_root(root, tables.probe_root(p, legal));
            same_root(root, tables.probe_root(p, p.legal_moves_direct()));
            check(p.fen() == original_fen && p.key == original_key && p.consistent(),
                  "Reused-list probe changed position");
            for (const auto& move : root.moves)
                check(bool(p.parse_uci(move.move.uci())), "Reader returned illegal move");
        }
        const auto mate = position("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1");
        const auto stalemate = position("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1");
        check(tables.probe_root(mate).wdl == 0 && !tables.probe_root(mate).suggested, "Mate root misclassified");
        check(tables.probe_root(stalemate).wdl == 2 && !tables.probe_root(stalemate).suggested, "Stalemate root misclassified");
        for (const auto& p : {mate, stalemate}) {
            auto copy = p;
            same_root(tables.probe_root(p), tables.probe_root(p, copy.legal_moves()));
            same_root(tables.probe_root(p), tables.probe_root(p, p.legal_moves_direct()));
        }
        check(tables.probe_root(queen, MoveList{}).status == ProbeStatus::Unavailable,
              "Empty incomplete list manufactured a terminal result");
        auto incomplete = queen_legal;
        check(incomplete.size() > 1, "Incomplete-list fixture needs multiple moves");
        --incomplete.count;
        check(tables.probe_root(queen, incomplete).status == ProbeStatus::Unavailable,
              "Nonempty incomplete list supplied a partial root result");
        check(tables.probe_root(queen, queen_legal, [] { return true; }).status == ProbeStatus::Unavailable,
              "Reused-list cancellation supplied a root result");
        // Switching to a missing dataset cannot reuse the original reader's maps,
        // and switching back must reactivate the intended dataset without a hit.
        Tablebases another("/also-not-an-orient-tablebase-directory", 0);
        check(another.probe_wdl(queen).status == ProbeStatus::Unavailable, "Dataset switch reused maps");
        const auto old_hits = tables.stats().cache_hits;
        check(tables.probe_wdl(queen).status == ProbeStatus::Success, "Original dataset did not reactivate");
        check(tables.stats().cache_hits == old_hits, "Dataset generation switch retained cached results");
        {
            // Cache-zero hot probes still synchronize the process-global reader.
            // They must reactivate their own path after another provider changes
            // it; caching Reader identity is never caching dataset identity.
            Tablebases uncached(dataset, 0);
            const auto first = uncached.stats();
            for (unsigned i = 0; i < 5; ++i)
                check(uncached.probe_wdl(queen).wdl == 4, "Cache-zero repeated outcome changed");
            check(uncached.stats().probes == first.probes + 5
                  && uncached.stats().hits == first.hits + 5
                  && uncached.stats().cache_hits == 0 && uncached.cache_bytes() == 0,
                  "Cache-zero probes changed counters or cached a result");
            const auto before_unsupported = uncached.stats();
            check(uncached.probe_wdl(clock).status == ProbeStatus::Unsupported
                  && uncached.probe_wdl(castle).status == ProbeStatus::Unsupported
                  && uncached.probe_wdl(Position{}).status == ProbeStatus::Unsupported,
                  "Hot-path unsupported domain changed");
            check(uncached.stats().probes == before_unsupported.probes,
                  "Unsupported hot-path queries entered the reader");
            TemporaryDirectory empty_directory;
            Tablebases empty(empty_directory.path.string(), 0);
            for (unsigned i = 0; i < 3; ++i) {
                check(empty.probe_wdl(queen).status == ProbeStatus::Unavailable
                      && empty.largest() == 0, "Empty provider borrowed another provider's tables");
                check(uncached.probe_wdl(queen).wdl == 4 && uncached.largest() == 5,
                      "Cache-zero provider failed to restore its own tables");
            }
            Tablebases cached(dataset, 1);
            check(cached.probe_wdl(queen).wdl == 4, "Same-path fixture could not cache a result");
            const auto cached_hits = cached.stats().cache_hits;
            // Construction deliberately forces reader reinitialization even
            // for an unchanged pathname, advancing its generation.
            Tablebases same_path(dataset, 0);
            check(same_path.probe_wdl(queen).wdl == 4, "Same-path reinitialization failed");
            check(cached.probe_wdl(queen).wdl == 4
                  && cached.stats().cache_hits == cached_hits,
                  "Same-path generation change retained a stale cached result");
            check(cached.probe_wdl(queen).wdl == 4
                  && cached.stats().cache_hits == cached_hits + 1,
                  "Unchanged-generation hot path lost a valid cached result");
            same_root(cached.probe_root(queen), same_path.probe_root(queen));
        }
        std::cout << "Real-table root overloads, exact cache capacity/identity and dataset generation checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
