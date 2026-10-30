// Reproducible rule-only fixtures and cache measurements; never training data.
#include "orient/search.hpp"
#include "orient/tablebases.hpp"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cctype>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef __unix__
#include <sys/resource.h>
#endif
using namespace orient;
using Clock = std::chrono::steady_clock;
double milliseconds(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}
std::vector<std::string> lines(const std::string& path) {
    std::ifstream file(path); if (!file) throw std::runtime_error("cannot open " + path);
    std::vector<std::string> result;
    for (std::string line; std::getline(file, line);) if (!line.empty()) result.push_back(line);
    return result;
}
Position position(const std::string& fen) {
    Position p; std::string error;
    if (!p.set_fen(fen, &error)) throw std::runtime_error(error);
    return p;
}
std::string placement(const std::array<char, 64>& board) {
    std::string fen;
    for (int rank = 7; rank >= 0; --rank) {
        int empty = 0;
        for (int file = 0; file < 8; ++file) {
            const char c = board[rank * 8 + file];
            if (!c) { ++empty; continue; }
            if (empty) { fen += char('0' + empty); empty = 0; }
            fen += c;
        }
        if (empty) fen += char('0' + empty);
        if (rank) fen += '/';
    }
    return fen;
}
void generate(const std::string& materials, const std::string& out, std::size_t count) {
    const auto classes = lines(materials);
    if (classes.empty()) throw std::runtime_error("empty material list");
    std::mt19937_64 random(20261027);
    std::set<std::string> seen;
    std::ofstream file(out); if (!file) throw std::runtime_error("cannot write fixtures");
    for (std::size_t n = 0; n < count; ++n) {
        const auto& material = classes[n % classes.size()];
        std::string pieces; bool black = false;
        for (char c : material) {
            if (c == 'v') { black = true; continue; }
            pieces += black ? char(std::tolower(static_cast<unsigned char>(c))) : c;
        }
        bool accepted = false;
        for (int attempt = 0; attempt < 100000 && !accepted; ++attempt) {
            std::array<char, 64> board{};
            for (char c : pieces) {
                int square;
                do { square = int(random() % 64); }
                while (board[square] || ((c == 'P' || c == 'p') && (square < 8 || square >= 56)));
                board[square] = c;
            }
            const auto fen = placement(board) + (random() & 1 ? " w - - 0 1" : " b - - 0 1");
            Position p;
            if (!p.set_fen(fen) || p.legal_moves().empty() || !seen.insert(fen).second) continue;
            file << fen << '\n'; accepted = true;
        }
        if (!accepted) throw std::runtime_error("could not generate " + material);
    }
    std::cout << "generated " << count << " positions across " << classes.size() << " material classes\n";
}
void mix(std::uint64_t& hash, std::uint64_t n) { hash = (hash ^ n) * 1099511628211ULL; }
void measure(const std::string& path, std::size_t cache, const std::string& fens,
             const std::string& search_fens, int depth) {
    std::vector<Position> positions, searches;
    for (const auto& fen : lines(fens)) positions.push_back(position(fen));
    for (const auto& fen : lines(search_fens)) searches.push_back(position(fen));
    auto started = Clock::now();
    auto tables = std::make_shared<Tablebases>(path, cache);
    const double startup = milliseconds(started);
    if (tables->largest() != 5) throw std::runtime_error("full dataset required");
    std::uint64_t hash = 1469598103934665603ULL, search_hash = hash;
    started = Clock::now();
    for (const auto& p : positions) {
        const auto value = tables->probe_wdl(p);
        if (value.status != ProbeStatus::Success) throw std::runtime_error("missing WDL fixture");
        mix(hash, std::uint64_t(value.wdl));
    }
    const double distinct = milliseconds(started);
    started = Clock::now();
    for (int repeat = 0; repeat < 3; ++repeat) for (const auto& p : positions) {
        const auto value = tables->probe_wdl(p);
        if (value.status != ProbeStatus::Success) throw std::runtime_error("missing repeated fixture");
        mix(hash, std::uint64_t(value.wdl));
    }
    const double warm = milliseconds(started);
    const auto lookup_stats = tables->stats();
    tables->clear_cache();
    Searcher search(16); search.set_tablebases(tables);
    SearchLimits limits; limits.depth = depth;
    std::atomic_bool stop{false}; std::uint64_t nodes = 0, hits = 0;
    started = Clock::now();
    for (const auto& p : searches) {
        search.clear();
        const auto result = search.search(p, limits, stop);
        mix(search_hash, result.best.value); mix(search_hash, std::uint64_t(result.score));
        mix(search_hash, result.nodes); nodes += result.nodes; hits += result.tablebase_hits;
    }
    const double searched = milliseconds(started);
    long rss = 0;
#ifdef __unix__
    rusage usage{}; if (getrusage(RUSAGE_SELF, &usage) == 0) rss = usage.ru_maxrss;
#endif
    std::cout << std::setprecision(10) << "{\"cache_mib\":" << cache
        << ",\"cache_bytes\":" << tables->cache_bytes() << ",\"startup_ms\":" << startup
        << ",\"distinct_lookup_ms\":" << distinct << ",\"warm_lookup_ms\":" << warm
        << ",\"search_ms\":" << searched << ",\"lookup_hash\":\"" << hash
        << "\",\"search_hash\":\"" << search_hash << "\",\"search_nodes\":" << nodes
        << ",\"search_tbhits\":" << hits << ",\"lookup_hits\":" << lookup_stats.hits
        << ",\"lookup_cache_hits\":" << lookup_stats.cache_hits << ",\"peak_rss_kib\":" << rss << "}\n";
}

struct ProfileCounters {
    std::uint64_t calls = 0, legal = 0, probe = 0, validation = 0, allocations = 0;
};
ProfileCounters profile_counters(const TablebaseStats& stats) {
#ifdef ORIENT_TABLEBASE_BASELINE
    (void)stats;
    return {};
#else
    return {stats.root_calls, stats.root_legal_ns, stats.root_probe_ns,
            stats.root_validation_ns, stats.root_allocations};
#endif
}
std::size_t entry_bytes(const Tablebases& tables) {
#ifdef ORIENT_TABLEBASE_BASELINE
    // Reproduce the pinned 015 entry's layout without accessing its private
    // implementation or changing that baseline's reader/search source.
    struct Board { std::array<std::uint64_t, 8> bits; unsigned ep; bool turn; };
    struct Entry { Board board; std::uint8_t wdl; bool valid; };
    (void)tables;
    return sizeof(Entry);
#else
    return tables.cache_entry_bytes();
#endif
}
std::size_t capacity(const Tablebases& tables) {
#ifdef ORIENT_TABLEBASE_BASELINE
    return tables.cache_bytes() / entry_bytes(tables);
#else
    return tables.cache_capacity();
#endif
}

// This mode deliberately shares one harness between frozen 015 and candidate
// builds. No whole-root result is cached by the caller. The root TT is cleared
// once per corpus repetition, not per position (which would predominantly time
// megabytes of unrelated hash clearing). Fixtures and their order are identical.
void experiment(const std::string& path, std::size_t cache, const std::string& fens,
                const std::string& search_fens, const std::string& root_fens,
                int depth, int repeats) {
    if (repeats < 1 || repeats > 100 || depth < 1 || depth > 32)
        throw std::runtime_error("experiment requires repeats 1..100 and depth 1..32");
    std::vector<Position> positions, searches, roots;
    for (const auto& fen : lines(fens)) positions.push_back(position(fen));
    for (const auto& fen : lines(search_fens)) searches.push_back(position(fen));
    for (const auto& fen : lines(root_fens)) roots.push_back(position(fen));
    if (positions.empty() || searches.empty() || roots.empty())
        throw std::runtime_error("all experiment corpora must be nonempty");
    auto started = Clock::now();
    auto tables = std::make_shared<Tablebases>(path, cache);
    const double startup = milliseconds(started);
    if (tables->largest() != 5) throw std::runtime_error("full dataset required");
    std::uint64_t lookup_hash = 1469598103934665603ULL;
    std::uint64_t search_hash = lookup_hash, root_hash = lookup_hash;
    double distinct = 0, warm = 0, searched = 0, rooted = 0;
    for (int repeat = 0; repeat < repeats; ++repeat) {
        tables->clear_cache();
        started = Clock::now();
        for (const auto& p : positions) {
            const auto value = tables->probe_wdl(p);
            if (value.status != ProbeStatus::Success) throw std::runtime_error("missing WDL fixture");
            mix(lookup_hash, std::uint64_t(value.wdl));
        }
        distinct += milliseconds(started);
        started = Clock::now();
        for (int warm_repeat = 0; warm_repeat < 3; ++warm_repeat)
            for (const auto& p : positions) {
                const auto value = tables->probe_wdl(p);
                if (value.status != ProbeStatus::Success) throw std::runtime_error("missing repeated WDL fixture");
                mix(lookup_hash, std::uint64_t(value.wdl));
            }
        warm += milliseconds(started);
    }
    const auto lookup_stats = tables->stats();
    Searcher search(16); search.set_tablebases(tables);
    SearchLimits limits; limits.depth = depth;
    std::atomic_bool stop{false};
    std::uint64_t search_nodes = 0, search_hits = 0;
    for (int repeat = 0; repeat < repeats; ++repeat) {
        tables->clear_cache();
        started = Clock::now();
        for (const auto& p : searches) {
            search.clear();
            const auto result = search.search(p, limits, stop);
            mix(search_hash, result.best.value); mix(search_hash, std::uint64_t(result.score));
            mix(search_hash, result.nodes); mix(search_hash, result.tablebase_hits);
            search_nodes += result.nodes; search_hits += result.tablebase_hits;
        }
        searched += milliseconds(started);
    }
    Searcher root_search(1); root_search.set_tablebases(tables);
    std::uint64_t root_nodes = 0, root_hits = 0, root_fallbacks = 0;
    std::uint64_t own_legal_ns = 0, adjudication_ns = 0;
    std::vector<std::uint64_t> latencies;
    latencies.reserve(roots.size() * std::size_t(repeats));
    const auto before_roots = profile_counters(tables->stats());
    for (int repeat = 0; repeat < repeats; ++repeat) {
        tables->clear_cache(); root_search.clear();
        started = Clock::now();
        for (const auto& p : roots) {
            const auto begin = Clock::now();
            const auto result = root_search.search(p, limits, stop);
            const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - begin).count();
            latencies.push_back(std::uint64_t(ns));
            mix(root_hash, result.best.value); mix(root_hash, std::uint64_t(result.score));
            mix(root_hash, result.nodes); mix(root_hash, result.tablebase_hits);
            root_nodes += result.nodes; root_hits += result.tablebase_hits;
            root_fallbacks += result.depth != 0;
#ifndef ORIENT_TABLEBASE_BASELINE
            own_legal_ns += result.profile_root_legal_ns;
            adjudication_ns += result.profile_root_adjudication_ns;
#endif
        }
        rooted += milliseconds(started);
    }
    const auto after_roots = profile_counters(tables->stats());
    std::sort(latencies.begin(), latencies.end());
    const auto percentile = [&](std::size_t percent) {
        return double(latencies[(latencies.size() - 1) * percent / 100]) / 1000.0;
    };
    const auto profile_legal = after_roots.legal - before_roots.legal;
    const auto profile_probe = after_roots.probe - before_roots.probe;
    const auto profile_validation = after_roots.validation - before_roots.validation;
    const bool profiling = own_legal_ns || adjudication_ns || profile_legal || profile_probe || profile_validation;
    long rss = 0;
#ifdef __unix__
    rusage usage{}; if (getrusage(RUSAGE_SELF, &usage) == 0) rss = usage.ru_maxrss;
#endif
    std::cout << std::setprecision(12)
        << "{\"cache_mib\":" << cache << ",\"cache_bytes\":" << tables->cache_bytes()
        << ",\"cache_entry_bytes\":" << entry_bytes(*tables) << ",\"cache_capacity\":" << capacity(*tables)
        << ",\"startup_ms\":" << startup << ",\"repeats\":" << repeats
        << ",\"positions\":" << positions.size() << ",\"search_positions\":" << searches.size()
        << ",\"root_positions\":" << roots.size() << ",\"depth\":" << depth
        << ",\"distinct_lookup_ms\":" << distinct << ",\"warm_lookup_ms\":" << warm
        << ",\"search_ms\":" << searched << ",\"root_ms\":" << rooted
        << ",\"root_latency_median_us\":" << percentile(50)
        << ",\"root_latency_p95_us\":" << percentile(95)
        << ",\"lookup_hash\":\"" << lookup_hash << "\",\"search_hash\":\"" << search_hash
        << "\",\"root_hash\":\"" << root_hash << "\",\"search_nodes\":" << search_nodes
        << ",\"search_tbhits\":" << search_hits << ",\"root_nodes\":" << root_nodes
        << ",\"root_tbhits\":" << root_hits << ",\"root_fallbacks\":" << root_fallbacks
        << ",\"lookup_hits\":" << lookup_stats.hits << ",\"lookup_cache_hits\":" << lookup_stats.cache_hits
        << ",\"peak_rss_kib\":" << rss << ",\"profiling_enabled\":" << (profiling ? "true" : "false")
        << ",\"profile_root_calls\":" << after_roots.calls - before_roots.calls
        << ",\"profile_root_legal_ns\":" << own_legal_ns + profile_legal
        << ",\"profile_root_fathom_ns\":" << profile_probe
        << ",\"profile_root_validation_ns\":" << profile_validation
        << ",\"profile_root_adjudication_ns\":" << adjudication_ns
        << ",\"root_result_allocations\":";
    if (profiling) std::cout << after_roots.allocations - before_roots.allocations;
    else std::cout << "null";
    std::cout << "}\n";
}
int main(int argc, char** argv) {
    try {
        if (argc == 5 && std::string(argv[1]) == "generate")
            generate(argv[2], argv[3], std::stoull(argv[4]));
        else if (argc == 7 && std::string(argv[1]) == "run")
            measure(argv[2], std::stoull(argv[3]), argv[4], argv[5], std::stoi(argv[6]));
        else if ((argc == 8 || argc == 9) && std::string(argv[1]) == "experiment")
            experiment(argv[2], std::stoull(argv[3]), argv[4], argv[5], argv[6], std::stoi(argv[7]),
                       argc == 9 ? std::stoi(argv[8]) : 1);
        else throw std::runtime_error("generate MATERIALS OUT COUNT | run TABLEPATH CACHE_MIB FENS SEARCH_FENS DEPTH | experiment TABLEPATH CACHE_MIB FENS SEARCH_FENS ROOT_FENS DEPTH [REPEATS]");
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
