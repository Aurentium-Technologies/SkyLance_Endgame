// Reader-owned payload diagnostics, kept separate from performance acceptance.
// Corpus positions and probe results are validation data, never training labels.
#include "orient/tablebases.hpp"
#include <orient_tb_diagnostics.h>
#include <tbprobe.h>

#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#ifdef __unix__
#include <sys/resource.h>
#endif
#ifdef __GLIBC__
#include <malloc.h>
#endif

#if !defined(ORIENT_FATHOM_DIAGNOSTICS) || !ORIENT_FATHOM_DIAGNOSTICS
#error "The reader-memory harness requires a diagnostic reader build"
#endif

namespace {
constexpr std::uint64_t HashSeed = 1469598103934665603ULL;

std::string quoted(std::string_view value) {
    constexpr char hex[] = "0123456789abcdef";
    std::string out = "\"";
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') { out += '\\'; out += char(c); }
        else if (c < 32) {
            out += "\\u00"; out += hex[c >> 4]; out += hex[c & 15];
        } else out += char(c);
    }
    return out + '"';
}

void mix(std::uint64_t& hash, std::uint64_t value) {
    hash = (hash ^ value) * 1099511628211ULL;
}

void hash_probe(std::uint64_t& hash, const orient::RootProbe& value) {
    if (value.status != orient::ProbeStatus::Success)
        throw std::runtime_error("memory corpus contains an unsuccessful root probe");
    mix(hash, std::uint64_t(value.status)); mix(hash, std::uint64_t(value.wdl));
    mix(hash, value.dtz); mix(hash, value.suggested.value); mix(hash, value.moves.size());
    for (const auto& move : value.moves) {
        mix(hash, move.move.value); mix(hash, std::uint64_t(move.wdl)); mix(hash, move.dtz);
    }
}

struct ProcessMemory {
    bool available = false;
    std::uint64_t virtual_bytes = 0, rss_bytes = 0, pss_bytes = 0;
    std::uint64_t anonymous_resident_bytes = 0;
    std::uint64_t private_clean_bytes = 0, private_dirty_bytes = 0;
    std::uint64_t table_virtual_bytes = 0, table_rss_bytes = 0, table_pss_bytes = 0;
    std::uint64_t table_anonymous_resident_bytes = 0, table_vma_count = 0;
};

bool table_path(std::string path, const std::string& root) {
    const std::string deleted = " (deleted)";
    if (path.ends_with(deleted)) path.resize(path.size() - deleted.size());
    if (!path.starts_with(root)) return false;
    return path.ends_with(".rtbw") || path.ends_with(".rtbz") || path.ends_with(".rtbm");
}

// Exact key parsing avoids adding Pss_Anon/Pss_File to Pss a second time. The
// caller supplies one canonical table-directory prefix, including its slash.
ProcessMemory parse_smaps(std::istream& input, const std::string& table_root) {
    ProcessMemory result;
    bool in_table = false, saw_mapping = false;
    for (std::string line; std::getline(input, line);) {
        std::istringstream fields(line);
        std::string first;
        fields >> first;
        const auto dash = first.find('-');
        if (dash != std::string::npos && first.find(':') == std::string::npos) {
            const auto start = std::stoull(first.substr(0, dash), nullptr, 16);
            const auto end = std::stoull(first.substr(dash + 1), nullptr, 16);
            if (end < start) throw std::runtime_error("invalid smaps address interval");
            std::string permissions, offset, device, inode, path;
            if (!(fields >> permissions >> offset >> device >> inode))
                throw std::runtime_error("invalid smaps mapping header");
            std::getline(fields, path);
            const auto begin = path.find_first_not_of(" \t");
            path = begin == std::string::npos ? "" : path.substr(begin);
            in_table = table_path(path, table_root);
            const auto bytes = end - start;
            result.virtual_bytes += bytes;
            if (in_table) { result.table_virtual_bytes += bytes; ++result.table_vma_count; }
            saw_mapping = true;
            continue;
        }
        if (first != "Rss:" && first != "Pss:" && first != "Anonymous:"
            && first != "Private_Clean:" && first != "Private_Dirty:") continue;
        std::uint64_t kib = 0; std::string unit;
        if (!(fields >> kib >> unit) || unit != "kB")
            throw std::runtime_error("invalid smaps memory unit");
        const auto bytes = kib * 1024;
        if (first == "Rss:") {
            result.rss_bytes += bytes;
            if (in_table) result.table_rss_bytes += bytes;
        } else if (first == "Pss:") {
            result.pss_bytes += bytes;
            if (in_table) result.table_pss_bytes += bytes;
        } else if (first == "Anonymous:") {
            result.anonymous_resident_bytes += bytes;
            if (in_table) result.table_anonymous_resident_bytes += bytes;
        } else if (first == "Private_Clean:") result.private_clean_bytes += bytes;
        else if (first == "Private_Dirty:") result.private_dirty_bytes += bytes;
    }
    result.available = saw_mapping && !input.bad();
    return result;
}

ProcessMemory process_memory(const std::string& table_root) {
#ifdef __linux__
    std::ifstream input("/proc/self/smaps");
    if (input) return parse_smaps(input, table_root);
#else
    (void)table_root;
#endif
    return {};
}

std::optional<std::uint64_t> peak_rss_bytes() {
#ifdef __unix__
    rusage usage{};
    if (getrusage(RUSAGE_SELF, &usage) == 0) {
#ifdef __APPLE__
        return std::uint64_t(usage.ru_maxrss);
#else
        return std::uint64_t(usage.ru_maxrss) * 1024;
#endif
    }
#endif
    return std::nullopt;
}

struct AllocatorMemory {
    bool available = false;
    std::uint64_t arena_bytes = 0, allocated_arena_bytes = 0, free_arena_bytes = 0;
    std::uint64_t malloc_mapping_bytes = 0, malloc_mapping_count = 0;
};

AllocatorMemory allocator_memory() {
#ifdef __GLIBC__
    const auto info = mallinfo2();
    return {true, std::uint64_t(info.arena), std::uint64_t(info.uordblks),
            std::uint64_t(info.fordblks), std::uint64_t(info.hblkhd), std::uint64_t(info.hblks)};
#else
    return {};
#endif
}

struct Snapshot {
    const char* phase;
    OrientTbDiagnostics reader{};
    AllocatorMemory allocator;
    ProcessMemory process;
    std::optional<std::uint64_t> peak_rss;
};

Snapshot snapshot(const char* phase, const std::string& table_root) {
    Snapshot value{};
    value.phase = phase;
    orient_tb_diagnostics_snapshot(&value.reader);
    // These are untimed diagnostics. /proc parsing and the harness itself are
    // ordinary process allocations, excluded from the reader's tagged payload.
    value.allocator = allocator_memory();
    value.process = process_memory(table_root);
    value.peak_rss = peak_rss_bytes();
    return value;
}

std::uint64_t live_bytes(const Snapshot& snapshot) {
    std::uint64_t bytes = 0;
    for (const auto& item : snapshot.reader.allocations) bytes += item.live_bytes;
    return bytes;
}

void optional_number(std::ostream& out, bool available, std::uint64_t value) {
    if (available) out << value;
    else out << "null";
}

void write_snapshot(std::ostream& out, const Snapshot& value) {
    const auto& r = value.reader; const auto& a = value.allocator; const auto& p = value.process;
    std::uint64_t category_peak_sum = 0;
    for (const auto& category : r.allocations) category_peak_sum += category.peak_bytes;
    out << "{\"reader_requested_live_bytes\":" << live_bytes(value)
        << ",\"reader_requested_category_peak_sum_bytes\":" << category_peak_sum
        << ",\"reader_known_control_static_bytes\":" << r.static_bytes
        << ",\"reader_mapped_bytes\":" << r.mapped_bytes
        << ",\"reader_peak_mapped_bytes\":" << r.peak_mapped_bytes
        << ",\"reader_map_calls\":" << r.map_calls << ",\"reader_unmap_calls\":" << r.unmap_calls
        << ",\"reader_open_attempts\":" << r.open_attempts
        << ",\"reader_open_successes\":" << r.open_successes
        << ",\"reader_open_failures\":" << r.open_failures
        << ",\"reader_piece_count\":" << r.piece_count << ",\"reader_pawn_count\":" << r.pawn_count
        << ",\"reader_piece_capacity\":" << r.piece_capacity
        << ",\"reader_pawn_capacity\":" << r.pawn_capacity << ",\"allocation_categories\":{";
    constexpr std::array<const char*, 3> names{"catalogue", "paths", "decoding"};
    for (std::size_t i = 0; i < names.size(); ++i) {
        const auto& category = r.allocations[i];
        if (i) out << ',';
        out << quoted(names[i]) << ":{\"live_bytes\":" << category.live_bytes
            << ",\"peak_bytes\":" << category.peak_bytes
            << ",\"allocations\":" << category.allocations << ",\"frees\":" << category.frees << '}';
    }
    out << "},\"allocator_stats_available\":" << (a.available ? "true" : "false");
    const auto allocator_field = [&](const char* key, std::uint64_t number) {
        out << ',' << quoted(key) << ':'; optional_number(out, a.available, number);
    };
    allocator_field("allocator_arena_bytes", a.arena_bytes);
    allocator_field("allocator_allocated_arena_bytes", a.allocated_arena_bytes);
    allocator_field("allocator_free_arena_bytes", a.free_arena_bytes);
    allocator_field("allocator_malloc_mapping_bytes", a.malloc_mapping_bytes);
    allocator_field("allocator_malloc_mapping_count", a.malloc_mapping_count);
    allocator_field("allocator_accounted_bytes", a.allocated_arena_bytes + a.malloc_mapping_bytes);
    out << ",\"smaps_available\":" << (p.available ? "true" : "false");
    const auto process_field = [&](const char* key, std::uint64_t number) {
        out << ',' << quoted(key) << ':'; optional_number(out, p.available, number);
    };
    process_field("process_virtual_bytes", p.virtual_bytes);
    process_field("process_current_rss_bytes", p.rss_bytes);
    process_field("process_pss_bytes", p.pss_bytes);
    process_field("process_anonymous_resident_bytes", p.anonymous_resident_bytes);
    process_field("process_private_clean_bytes", p.private_clean_bytes);
    process_field("process_private_dirty_bytes", p.private_dirty_bytes);
    process_field("table_mapping_virtual_bytes", p.table_virtual_bytes);
    process_field("table_mapping_rss_bytes", p.table_rss_bytes);
    process_field("table_mapping_pss_bytes", p.table_pss_bytes);
    process_field("table_mapping_anonymous_resident_bytes", p.table_anonymous_resident_bytes);
    process_field("table_mapping_vma_count", p.table_vma_count);
    out << ",\"process_peak_rss_bytes\":";
    optional_number(out, value.peak_rss.has_value(), value.peak_rss.value_or(0));
    out << '}';
}

bool next_fen(std::istream& input, std::string& fen) {
    while (std::getline(input, fen)) {
        if (!fen.empty() && fen.back() == '\r') fen.pop_back();
        if (fen.find_first_not_of(" \t") != std::string::npos) return true;
    }
    if (input.bad()) throw std::runtime_error("error reading memory corpus");
    return false;
}

void self_test() {
    std::istringstream smaps(
        "1000-3000 r--s 00000000 00:01 1 /table dir/KQvK.rtbw\n"
        "Size: 8 kB\nRss: 4 kB\nPss: 2 kB\nPss_File: 2 kB\nAnonymous: 0 kB\n"
        "Private_Clean: 1 kB\nPrivate_Dirty: 0 kB\n"
        "4000-5000 rw-p 00000000 00:00 0 [heap]\n"
        "Rss: 4 kB\nPss: 4 kB\nAnonymous: 4 kB\nPrivate_Dirty: 4 kB\n"
        "6000-7000 r--s 00000000 00:01 2 /table directory/KRvK.rtbw\n"
        "Rss: 4 kB\nPss: 4 kB\nAnonymous: 0 kB\n");
    const auto p = parse_smaps(smaps, "/table dir/");
    if (!p.available || p.virtual_bytes != 16384 || p.rss_bytes != 12288
        || p.pss_bytes != 10240 || p.anonymous_resident_bytes != 4096
        || p.table_virtual_bytes != 8192 || p.table_rss_bytes != 4096
        || p.table_pss_bytes != 2048 || p.table_vma_count != 1)
        throw std::runtime_error("smaps attribution self-test failed");
    if (quoted("a\n\"\\\t") != "\"a\\u000a\\\"\\\\\\u0009\"")
        throw std::runtime_error("JSON quoting self-test failed");
    if (!table_path("/table dir/KQvK.rtbz (deleted)", "/table dir/")
        || table_path("/elsewhere/KQvK.rtbw", "/table dir/"))
        throw std::runtime_error("table filename attribution self-test failed");
    std::cout << "Reader-memory smaps attribution and JSON self-tests passed\n";
}
} // namespace

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string_view(argv[1]) == "--selftest") { self_test(); return 0; }
        if (argc != 3) throw std::runtime_error("usage: TABLEPATH CORPUS (or --selftest)");
        const auto canonical_tables = std::filesystem::weakly_canonical(argv[1]).string();
        const auto table_root = canonical_tables.ends_with('/') ? canonical_tables : canonical_tables + '/';
        std::ifstream input(argv[2]);
        if (!input) throw std::runtime_error("cannot open memory corpus");
        std::string fen, error;
        if (!next_fen(input, fen)) throw std::runtime_error("empty memory corpus");
        orient::Position position;
        if (!position.set_fen(fen, &error)) throw std::runtime_error("invalid first memory FEN: " + error);
        std::array<Snapshot, 6> phases;
        phases[0] = snapshot("before_init", table_root);
        auto tables = std::make_unique<orient::Tablebases>(canonical_tables, 0);
        if (tables->largest() != 5 || tables->cache_bytes() != 0)
            throw std::runtime_error("complete five-piece collection and disabled result cache required");
        phases[1] = snapshot("after_init", table_root);
        std::uint64_t semantic_hash = HashSeed;
        hash_probe(semantic_hash, tables->probe_root(position));
        std::size_t positions = 1;
        phases[2] = snapshot("after_first_probe", table_root);
        while (next_fen(input, fen)) {
            if (!position.set_fen(fen, &error)) throw std::runtime_error("invalid memory FEN: " + error);
            hash_probe(semantic_hash, tables->probe_root(position));
            ++positions;
        }
        phases[3] = snapshot("after_full_sweep", table_root);
        tables.reset();
        // The adapter's process-global reader deliberately retains its current
        // dataset. Record that state; do not label adapter destruction teardown.
        phases[4] = snapshot("after_adapter_destruction", table_root);
        // Isolated diagnostic process, no live providers, no further probes.
        // This is explicit reader teardown, not a production lifetime change.
        tb_free();
        phases[5] = snapshot("after_explicit_teardown", table_root);
        if (live_bytes(phases[5]) != 0 || phases[5].reader.mapped_bytes != 0
            || (phases[5].process.available && phases[5].process.table_virtual_bytes != 0))
            throw std::runtime_error("explicit teardown retained reader allocations or table mappings");
        for (const auto& category : phases[5].reader.allocations)
            if (category.allocations != category.frees)
                throw std::runtime_error("explicit teardown has unmatched reader allocation calls");
        if (phases[5].reader.map_calls != phases[5].reader.unmap_calls)
            throw std::runtime_error("explicit teardown has unmatched successful mapping calls");
        std::cout << "{\"schema_version\":1,\"mode\":\"memory\",\"diagnostics_enabled\":true"
            << ",\"cache_bytes\":0,\"positions\":" << positions
            << ",\"semantic_hash\":\"" << semantic_hash << "\",\"table_path\":" << quoted(canonical_tables)
            << ",\"corpus\":" << quoted(argv[2])
            << ",\"native_positions_retained\":1,\"position_object_bytes\":" << sizeof(position)
            << ",\"position_history_capacity_bytes\":" << position.history.capacity() * sizeof(std::uint64_t)
            << ",\"notes\":{\"allocation_scope\":\"reader-tagged requested payload; diagnostic bookkeeping, adapter objects and corpus storage excluded\""
            << ",\"allocator_scope\":\"whole-process glibc arena allocations plus malloc-backed mappings; includes other objects and allocator overhead\""
            << ",\"rss_scope\":\"whole diagnostic process; table mapping residency separated; kernel page cache outside the process is not measured\""
            << ",\"static_scope\":\"known mutable reader hash/control storage only; excludes read-only encoding and attack tables, diagnostic ledgers and other ELF sections\""
            << ",\"peak_scope\":\"sum of category peaks is not a simultaneous total peak\""
            << ",\"lifetime\":\"adapter destruction retains global resources; explicit reader teardown follows with no live provider or later probes\"},\"phases\":{";
        for (std::size_t i = 0; i < phases.size(); ++i) {
            if (i) std::cout << ',';
            std::cout << quoted(phases[i].phase) << ':'; write_snapshot(std::cout, phases[i]);
        }
        std::cout << "}}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
