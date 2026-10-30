// Native query-stack comparison harness. No search, games or training labels.
#include "orient/tablebases.hpp"
#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef __unix__
#include <sys/resource.h>
#endif

namespace O = orient;
using Clock = std::chrono::steady_clock;
extern "C" int orient_comparison_dtz(const std::uint64_t*, unsigned, unsigned, bool, int*);

namespace {
constexpr std::uint64_t HashSeed = 1469598103934665603ULL;
struct Fixture {
    O::Position position;
    std::string fen, parse_error;
    bool parsed = false, terminal = false, checkmate = false;
};
struct Alternative {
    O::Move move;
    std::string uci;
    int wdl = 2;
    unsigned dtz = 0;
};
struct Result {
    O::ProbeStatus status = O::ProbeStatus::Unavailable;
    int wdl = 2, signed_dtz = 0;
    unsigned dtz = 0;
    O::Move suggested;
    std::vector<Alternative> moves;
};

std::string quoted(const std::string& text) {
    std::string out = "\"";
    for (unsigned char c : text) {
        if (c == '\\' || c == '"') { out += '\\'; out += char(c); }
        else if (c == '\n') out += "\\n";
        else if (c == '\r') out += "\\r";
        else if (c == '\t') out += "\\t";
        else if (c < 32) throw std::runtime_error("control byte in input/diagnostic");
        else out += char(c);
    }
    return out + '"';
}
double ms(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}
double cpu_ms() {
#ifdef __unix__
    rusage u{};
    if (getrusage(RUSAGE_SELF, &u) == 0)
        return double(u.ru_utime.tv_sec + u.ru_stime.tv_sec) * 1000.0
             + double(u.ru_utime.tv_usec + u.ru_stime.tv_usec) / 1000.0;
#endif
    return 0;
}
long peak_rss() {
#ifdef __unix__
    rusage u{};
    if (getrusage(RUSAGE_SELF, &u) == 0) return u.ru_maxrss;
#endif
    return 0;
}
int nominal_wdl(int d, int halfmove) {
    const auto value = std::int64_t(d);
    return d > 0 ? (value + halfmove <= 100 ? 4 : 3)
         : d < 0 ? (-value + halfmove <= 100 ? 0 : 1) : 2;
}
std::array<std::uint64_t, 8> board_bits(const O::Position& p) {
    return {p.occupied[O::White], p.occupied[O::Black],
            p.bb[O::White][O::King] | p.bb[O::Black][O::King],
            p.bb[O::White][O::Queen] | p.bb[O::Black][O::Queen],
            p.bb[O::White][O::Rook] | p.bb[O::Black][O::Rook],
            p.bb[O::White][O::Bishop] | p.bb[O::Black][O::Bishop],
            p.bb[O::White][O::Knight] | p.bb[O::Black][O::Knight],
            p.bb[O::White][O::Pawn] | p.bb[O::Black][O::Pawn]};
}
bool root_eligible(const Fixture& f) {
    const auto& p = f.position;
    return f.parsed && p.castling == 0 && std::popcount(p.occupancy()) <= 5
        && p.halfmove >= 0 && p.halfmove < 100;
}
Result query(O::Tablebases& tables, const Fixture& f, const std::string& mode) {
    if (!f.parsed) return {O::ProbeStatus::Unsupported};
    if (mode == "wdl") {
        const auto value = tables.probe_wdl(f.position);
        Result out; out.status = value.status; out.wdl = value.wdl;
        return out;
    }
    if (!root_eligible(f)) return {O::ProbeStatus::Unsupported};
    if (mode == "dtz") {
        Result out;
        if (f.terminal) {
            out.status = O::ProbeStatus::Success;
            out.wdl = f.checkmate ? 0 : 2;
            return out;
        }
        const auto bits = board_bits(f.position);
        int success = 1;
        const int d = orient_comparison_dtz(bits.data(), unsigned(f.position.halfmove),
                    f.position.ep < 0 ? 0u : unsigned(f.position.ep),
                    f.position.side == O::White, &success);
        if (!success) return out;
        out.status = O::ProbeStatus::Success; out.signed_dtz = d;
        out.dtz = unsigned(d < 0 ? -std::int64_t(d) : std::int64_t(d));
        out.wdl = nominal_wdl(d, f.position.halfmove);
        return out;
    }
    if (mode != "all_moves") throw std::runtime_error("unknown query mode");
    auto root = tables.probe_root(f.position);
    Result out; out.status = root.status;
    if (root.status != O::ProbeStatus::Success) return out;
    out.wdl = root.wdl; out.dtz = root.dtz; out.suggested = root.suggested;
    out.moves.reserve(root.moves.size());
    for (const auto& item : root.moves)
        out.moves.push_back({item.move, item.move.uci(), item.wdl, item.dtz});
    std::sort(out.moves.begin(), out.moves.end(), [](const auto& a, const auto& b) { return a.uci < b.uci; });
    return out;
}
std::uint64_t move_code(O::Move m) {
    unsigned promotion = 0;
    switch (m.promotion()) {
    case O::Empty: break;
    case O::Queen: promotion = 1; break;
    case O::Rook: promotion = 2; break;
    case O::Bishop: promotion = 3; break;
    case O::Knight: promotion = 4; break;
    default: throw std::runtime_error("invalid promotion in reader output");
    }
    return std::uint64_t(m.from()) | (std::uint64_t(m.to()) << 6) | (std::uint64_t(promotion) << 12);
}
void mix(std::uint64_t& hash, std::uint64_t value) { hash = (hash ^ value) * 1099511628211ULL; }
void hash_result(std::uint64_t& hash, const Result& value, const std::string& mode) {
    mix(hash, std::uint64_t(value.status));
    if (value.status != O::ProbeStatus::Success) return;
    mix(hash, std::uint64_t(value.wdl));
    if (mode == "wdl") return;
    mix(hash, value.dtz);
    if (mode != "all_moves") return;
    mix(hash, value.moves.size());
    for (const auto& m : value.moves) { mix(hash, move_code(m.move)); mix(hash, std::uint64_t(m.wdl)); mix(hash, m.dtz); }
}
void verify_rows(O::Tablebases& tables, const std::vector<Fixture>& fixtures) {
    std::size_t line = 0;
    for (const auto& f : fixtures) {
        const auto raw = query(tables, f, "wdl"), dtz = query(tables, f, "dtz"), root = query(tables, f, "all_moves");
        std::cout << "{\"line\":" << ++line << ",\"fen\":" << quoted(f.fen)
            << ",\"parse_ok\":" << (f.parsed ? "true" : "false") << ",\"parse_error\":" << quoted(f.parse_error)
            << ",\"status\":" << int(raw.status) << ",\"wdl\":" << raw.wdl
            << ",\"dtz_status\":" << int(dtz.status) << ",\"signed_dtz\":" << dtz.signed_dtz
            << ",\"nominal_wdl\":" << dtz.wdl << ",\"dtz\":" << dtz.dtz
            << ",\"root_status\":" << int(root.status) << ",\"root_wdl\":" << root.wdl
            << ",\"root_dtz\":" << root.dtz << ",\"suggested\":" << quoted(root.suggested ? root.suggested.uci() : "0000")
            << ",\"dtz_rounded\":null,\"moves\":[";
        bool first = true;
        for (const auto& m : root.moves) {
            if (!first) std::cout << ',';
            first = false;
            std::cout << '[' << quoted(m.uci) << ',' << m.wdl << ',' << m.dtz << ']';
        }
        std::cout << "]}\n";
    }
}
}

int main(int argc, char** argv) {
    try {
        if (argc < 5 || argc > 6) throw std::runtime_error("TABLEPATH CORPUS MODE REPEATS [mmap]");
        const std::string mode = argv[3];
        if (mode != "wdl" && mode != "dtz" && mode != "all_moves" && mode != "verify")
            throw std::runtime_error("mode must be wdl, dtz, all_moves or verify");
        const int repeats = std::stoi(argv[4]);
        if (repeats < 1 || repeats > 100) throw std::runtime_error("repeats must be 1..100");
        if (argc == 6 && std::string(argv[5]) != "mmap") throw std::runtime_error("Orient backend must be mmap");
        std::ifstream file(argv[2]); if (!file) throw std::runtime_error("cannot open corpus");
        std::vector<std::string> fens;
        for (std::string fen; std::getline(file, fen);) if (!fen.empty()) fens.push_back(fen);
        if (fens.empty()) throw std::runtime_error("empty corpus");
        std::vector<Fixture> fixtures; fixtures.reserve(fens.size());
        for (const auto& fen : fens) {
            Fixture f; f.fen = fen; f.parsed = f.position.set_fen(fen, &f.parse_error);
            if (f.parsed) { auto copy = f.position; const auto legal = copy.legal_moves(); f.terminal = legal.empty(); f.checkmate = f.terminal && f.position.in_check(); }
            fixtures.push_back(std::move(f));
        }
        auto start = Clock::now();
        O::Tablebases tables(argv[1], 0);
        const double startup = ms(start);
        if (tables.largest() != 5) throw std::runtime_error("complete five-piece collection required");
        const long rss_before = peak_rss();
        if (mode == "verify") { verify_rows(tables, fixtures); return 0; }
        std::uint64_t first_hash = HashSeed;
        start = Clock::now(); double cpu = cpu_ms();
        for (const auto& f : fixtures) hash_result(first_hash, query(tables, f, mode), mode);
        const double first_ms = ms(start), first_cpu = cpu_ms() - cpu;
        std::vector<std::uint64_t> latency; latency.reserve(fixtures.size() * std::size_t(repeats));
        std::uint64_t hash = HashSeed;
        start = Clock::now(); cpu = cpu_ms();
        for (int r = 0; r < repeats; ++r) for (const auto& f : fixtures) {
            const auto call_start = Clock::now(); const auto value = query(tables, f, mode);
            latency.push_back(std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - call_start).count()));
            if (value.status != O::ProbeStatus::Success) throw std::runtime_error("timing corpus contains unsuccessful query");
            hash_result(hash, value, mode);
        }
        const double wall = ms(start), process_cpu = cpu_ms() - cpu;
        std::sort(latency.begin(), latency.end());
        const auto percentile = [&](unsigned p) { return double(latency[(latency.size() - 1) * p / 100]) / 1000.0; };
        std::cout << std::setprecision(12) << "{\"mode\":" << quoted(mode)
            << ",\"backend\":\"mmap\",\"positions\":" << fixtures.size() << ",\"repeats\":" << repeats
            << ",\"calls\":" << fixtures.size() * std::size_t(repeats)
            << ",\"semantic_hash\":\"" << hash << "\",\"wall_ms\":" << wall << ",\"cpu_ms\":" << process_cpu
            << ",\"p50_us\":" << percentile(50) << ",\"p95_us\":" << percentile(95)
            << ",\"startup_ms\":" << startup << ",\"first_pass_ms\":" << first_ms
            << ",\"first_pass_cpu_ms\":" << first_cpu << ",\"first_pass_hash\":\"" << first_hash
            << "\",\"peak_rss_kib\":" << peak_rss() << ",\"rss_before_probes_kib\":" << rss_before
            << ",\"cache_bytes\":" << tables.cache_bytes() << ",\"profiling_enabled\":false}\n";
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
