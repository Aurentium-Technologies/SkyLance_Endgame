// Complete adapter probes, measured separately from Orient searches.
// Fixtures and answers are validation data, never training labels.
#include "orient/tablebases.hpp"
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef __unix__
#include <sys/resource.h>
#endif
#ifdef __GLIBC__
#include <malloc.h>
#endif

using namespace orient;
using Clock = std::chrono::steady_clock;
double ms(Clock::time_point t) {
    return std::chrono::duration<double, std::milli>(Clock::now() - t).count();
}
double cpu_ms() {
#ifdef __unix__
    rusage u{};
    if (getrusage(RUSAGE_SELF, &u) == 0)
        return (u.ru_utime.tv_sec + u.ru_stime.tv_sec) * 1000.0
            + (u.ru_utime.tv_usec + u.ru_stime.tv_usec) / 1000.0;
#endif
    return 0;
}
long peak_rss() {
#ifdef __unix__
    rusage u{}; if (getrusage(RUSAGE_SELF, &u) == 0) return u.ru_maxrss;
#endif
    return 0;
}
std::size_t heap_bytes() {
#ifdef __GLIBC__
    return mallinfo2().uordblks;
#else
    return 0;
#endif
}
void mix(std::uint64_t& h, std::uint64_t value) { h = (h ^ value) * 1099511628211ULL; }
void hash_probe(std::uint64_t& h, const RootProbe& r) {
    if (r.status != ProbeStatus::Success) throw std::runtime_error("unavailable corpus root");
    mix(h, std::uint64_t(r.status)); mix(h, std::uint64_t(r.wdl)); mix(h, r.dtz);
    mix(h, r.suggested.value); mix(h, r.moves.size());
    for (const auto& m : r.moves) { mix(h, m.move.value); mix(h, std::uint64_t(m.wdl)); mix(h, m.dtz); }
}
int main(int argc, char** argv) {
    try {
        if (argc != 4) throw std::runtime_error("TABLEPATH FENS REPEATS");
        const int repeats = std::stoi(argv[3]);
        if (repeats < 1 || repeats > 100) throw std::runtime_error("repeats must be 1..100");
        std::ifstream input(argv[2]); if (!input) throw std::runtime_error("cannot open corpus");
        std::vector<Position> positions;
        for (std::string fen; std::getline(input, fen);) {
            if (fen.empty()) continue;
            positions.emplace_back(); std::string error;
            if (!positions.back().set_fen(fen, &error)) throw std::runtime_error(error);
        }
        if (positions.empty()) throw std::runtime_error("empty corpus");
        auto begin = Clock::now(); const double init_cpu = cpu_ms();
        Tablebases tables(argv[1], 0);
        const double startup = ms(begin), startup_cpu = cpu_ms() - init_cpu;
        if (tables.largest() != 5) throw std::runtime_error("complete five-piece dataset required");
        const auto heap_initial = heap_bytes(); const auto rss_initial = peak_rss();
        // This also initializes lazy file mappings. It is reported separately;
        // acceptance sweeps exclude first-use mapping and table setup.
        std::uint64_t first_hash = 1469598103934665603ULL;
        begin = Clock::now(); const double first_cpu = cpu_ms();
        for (const auto& p : positions) hash_probe(first_hash, tables.probe_root(p));
        const double first_ms = ms(begin), first_cpu_ms = cpu_ms() - first_cpu;
        std::uint64_t distinct_hash = 1469598103934665603ULL, hot_hash = distinct_hash;
        std::vector<std::uint64_t> latency;
        latency.reserve(positions.size() * std::size_t(repeats));
        begin = Clock::now(); const double distinct_cpu = cpu_ms();
        for (int r = 0; r < repeats; ++r) for (const auto& p : positions) {
            const auto start = Clock::now(); const auto value = tables.probe_root(p);
            latency.push_back(std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count()));
            hash_probe(distinct_hash, value);
        }
        const double distinct_ms = ms(begin), distinct_cpu_ms = cpu_ms() - distinct_cpu;
        const std::size_t hot_count = std::min<std::size_t>(145, positions.size());
        begin = Clock::now(); const double hot_cpu = cpu_ms();
        for (int r = 0; r < repeats; ++r) for (int round = 0; round < 32; ++round)
            for (std::size_t i = 0; i < hot_count; ++i) hash_probe(hot_hash, tables.probe_root(positions[i]));
        const double hot_ms = ms(begin), hot_cpu_ms = cpu_ms() - hot_cpu;
        std::sort(latency.begin(), latency.end());
        const auto quantile = [&](std::size_t percent) { return latency[(latency.size() - 1) * percent / 100] / 1000.0; };
        std::cout << std::setprecision(12)
            << "{\"profiling_enabled\":false,\"cache_bytes\":" << tables.cache_bytes()
            << ",\"positions\":" << positions.size() << ",\"repeats\":" << repeats
            << ",\"startup_ms\":" << startup << ",\"startup_cpu_ms\":" << startup_cpu
            << ",\"first_sweep_ms\":" << first_ms << ",\"first_sweep_cpu_ms\":" << first_cpu_ms
            << ",\"distinct_probe_ms\":" << distinct_ms << ",\"distinct_probe_cpu_ms\":" << distinct_cpu_ms
            << ",\"hot_probe_ms\":" << hot_ms << ",\"hot_probe_cpu_ms\":" << hot_cpu_ms
            << ",\"hot_positions\":" << hot_count << ",\"hot_rounds\":32"
            << ",\"probe_latency_median_us\":" << quantile(50) << ",\"probe_latency_p95_us\":" << quantile(95)
            << ",\"first_hash\":\"" << first_hash << "\",\"distinct_hash\":\"" << distinct_hash
            << "\",\"hot_hash\":\"" << hot_hash << "\",\"peak_rss_kib\":" << peak_rss()
            << ",\"rss_before_probes_kib\":" << rss_initial << ",\"heap_before_probes_bytes\":" << heap_initial
            << ",\"heap_after_probes_bytes\":" << heap_bytes() << "}\n";
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
