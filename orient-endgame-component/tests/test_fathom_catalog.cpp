// Five-piece catalogue/discovery and exact diagnostic accounting; no engine link.
#include <array>
#include <chrono>
#include <cstdlib>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

#define ORIENT_FATHOM_CATALOG_TEST 1
#include "../third_party/fathom/src/tbprobe.c"
#undef min
#undef max

namespace {
namespace fs = std::filesystem;
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
OrientTbDiagnostics snapshot() { OrientTbDiagnostics result{}; orient_tb_diagnostics_snapshot(&result); return result; }
void all_released() {
    const auto s = snapshot();
    for (const auto& category : s.allocations) {
        check(category.live_bytes == 0, "Reader requested bytes survive explicit teardown");
        check(category.allocations == category.frees, "Allocation/free counts differ after teardown");
    }
    check(s.mapped_bytes == 0 && s.map_calls == s.unmap_calls, "Mapping survives explicit teardown");
    check(s.piece_count == 0 && s.pawn_count == 0, "Catalogue counts survive explicit teardown");
    check(TB_LARGEST == 0, "Teardown retains reported cardinality");
    check(TB_MaxCardinality == 0 && TB_MaxCardinalityDTM == 0,
          "Teardown retains internal cardinality");
    for (const auto& entry : tbHash)
        check(entry.key == 0 && entry.ptr == nullptr, "Teardown retains catalogue hash pointers");
}
struct TemporaryDirectory {
    fs::path path = fs::temp_directory_path() / ("Orient catalogue " + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    TemporaryDirectory() { check(fs::create_directory(path), "Cannot create temporary directory"); }
    ~TemporaryDirectory() { std::error_code ignored; fs::remove_all(path, ignored); }
};
void link_or_copy(const fs::path& source, const fs::path& target) {
    std::error_code error;
    fs::create_symlink(fs::absolute(source), target, error);
    if (error) fs::copy_file(source, target);
}
constexpr std::uint64_t WhitePieces = 9, BlackPieces = UINT64_C(1) << 62;
unsigned queen_wdl() {
    return tb_probe_wdl(WhitePieces, BlackPieces, 1 | BlackPieces, 8, 0, 0, 0, 0, 0, 0, 0, true);
}
unsigned queen_root() {
    std::array<unsigned, TB_MAX_MOVES> alternatives{};
    return tb_probe_root(WhitePieces, BlackPieces, 1 | BlackPieces, 8, 0, 0, 0, 0,
                         0, 0, 0, true, alternatives.data());
}
void bare_directory_tests() {
    static_assert(TB_PIECES == 7, "Encoding dimensions must stay seven");
    static_assert(TB_HASHBITS == 12, "Material hash must stay4096slots");
    static_assert(ORIENT_TB_MAX_PIECE == 84 && ORIENT_TB_MAX_PAWN == 61);
    static_assert(sizeof(((EncInfo*)nullptr)->pieces) == 7);
    static_assert(sizeof(((PairsData*)nullptr)->prefixLen) == 256);
    tb_free(); all_released();
    TemporaryDirectory directory;
    auto before = snapshot();
    check(tb_init(directory.path.string().c_str()), "Empty directory initialization failed");
    auto after = snapshot();
    check(TB_LARGEST == 0 && after.piece_count == 0 && after.pawn_count == 0, "Empty catalogue reported material");
    check(after.piece_capacity == 84 && after.pawn_capacity == 61, "Wrong catalogue capacities");
    check(after.open_attempts - before.open_attempts == 145, "Empty catalogue did not stop at145WDLnames");
    check(after.open_failures - before.open_failures == 145, "Empty catalogue failed-open count differs");
    check(after.allocations[ORIENT_TB_CATALOG].live_bytes == 84 * sizeof(PieceEntry) + 61 * sizeof(PawnEntry), "Catalogue accounting differs from requested payload");
    check(after.allocations[ORIENT_TB_PATHS].live_bytes == directory.path.string().size() + 1 + sizeof(char*), "Persistent path payload accounting differs");
    check(after.allocations[ORIENT_TB_PAIRS].live_bytes == 0 && after.mapped_bytes == 0, "Initialization eagerly loaded table data");
    check(queen_wdl() == TB_RESULT_FAILED, "Empty collection manufactured an outcome");
    tb_free(); all_released();
    before = snapshot();
    check(tb_init((directory.path / "missing").string().c_str()), "Missing directory initialization contract changed");
    after = snapshot();
    check(after.open_attempts - before.open_attempts == 145 && TB_LARGEST == 0, "Missing collection discovery differs");
    tb_free(); all_released();
    check(tb_init(""), "Empty path initialization failed");
    check(tb_init("<empty>"), "Empty-path sentinel failed");
    tb_free(); all_released();
}
void real_directory_tests(const fs::path& dataset) {
    TemporaryDirectory partial;
    link_or_copy(dataset / "KQvK.rtbw", partial.path / "KQvK.rtbw");
    // Six/seven-piece names contain valid aligned bytes but must never be opened.
    link_or_copy(dataset / "KQvK.rtbw", partial.path / "KQQQvKQ.rtbw");
    link_or_copy(dataset / "KQvK.rtbw", partial.path / "KQQQQvKQ.rtbw");
    auto before = snapshot();
    check(tb_init(partial.path.string().c_str()), "Partial collection initialization failed");
    auto after = snapshot();
    check(TB_LARGEST == 3 && after.piece_count == 1 && after.pawn_count == 0, "Partial collection cardinality/counts differ");
    check(after.open_attempts - before.open_attempts == 147, "Discovery opened unsupported material names");
    check(after.open_successes - before.open_successes == 1, "Unexpected partial collection opens");
    check(queen_wdl() == TB_WIN, "Partial WDL collection failed a covered query");
    check(queen_root() == TB_RESULT_FAILED, "Missing DTZ manufactured a complete root value");
    check(snapshot().mapped_bytes > 0 && snapshot().allocations[ORIENT_TB_PAIRS].live_bytes > 0, "Probe metadata/mappings were not tracked");
    tb_free(); all_released();

    // Preserve DTM discovery while leaving decoder behavior/format unchanged.
    link_or_copy(dataset / "KQvK.rtbw", partial.path / "KQvK.rtbm");
    check(tb_init(partial.path.string().c_str()) && numDtm == 1, "DTM discovery was removed");
    tb_free(); all_released();
    fs::remove(partial.path / "KQvK.rtbm");
    link_or_copy(dataset / "KQvK.rtbz", partial.path / "KQvK.rtbz");
    check(tb_init(partial.path.string().c_str()) && queen_root() != TB_RESULT_FAILED, "Partial WDL/DTZ collection failed");
    const auto catalogue_allocations = snapshot().allocations[ORIENT_TB_CATALOG].allocations;
    check(tb_init(partial.path.string().c_str()) && queen_wdl() == TB_WIN, "Same-path reinitialization failed");
    check(snapshot().allocations[ORIENT_TB_CATALOG].allocations == catalogue_allocations, "Same-path reinit unnecessarily allocated another catalogue");
    check(tb_init(dataset.string().c_str()), "Complete collection initialization failed");
    after = snapshot();
    check(TB_LARGEST == 5 && after.piece_count == 84 && after.pawn_count == 61, "Complete five-piece catalogue coverage differs");
    check(numWdl == 145 && numDtz == 145 && numDtm == 0, "Complete dataset discovery counts differ");
    check(queen_wdl() == TB_WIN && queen_root() != TB_RESULT_FAILED, "Complete collection query failed");
    tb_free(); all_released();

    // Deliberately lower test-only insertion limits; production capacities stay84/61.
    for (bool pawn : {false, true}) {
        if (pawn) orientTbPawnLimit = 0; else orientTbPieceLimit = 0;
        check(!tb_init(dataset.string().c_str()), "Capacity exhaustion silently accepted partial coverage");
        check(TB_LARGEST == 0 && TB_MaxCardinality == 0 && TB_MaxCardinalityDTM == 0, "Failed capacity initialization retained cardinality");
        check(queen_wdl() == TB_RESULT_FAILED, "Failed capacity initialization retained a stale hash entry");
        for (const auto& entry : tbHash) check(entry.ptr == nullptr && entry.key == 0, "Capacity rollback retained catalogue hash pointers");
        all_released();
        orientTbPawnLimit = ORIENT_TB_MAX_PAWN; orientTbPieceLimit = ORIENT_TB_MAX_PIECE;
        check(tb_init(dataset.string().c_str()) && queen_wdl() == TB_WIN, "Cannot recover after capacity rollback");
        tb_free(); all_released();
    }
}
}
int main(int argc, char** argv) {
    try {
        bare_directory_tests();
        const char* dataset = argc > 1 ? argv[1] : std::getenv("ORIENT_SYZYGY_PATH");
        if (dataset && *dataset) real_directory_tests(dataset);
        std::cout << "Five-piece catalogue, discovery, accounting, teardown and capacity rollback checks passed";
        if (!dataset || !*dataset) std::cout << " (real-table cases require ORIENT_SYZYGY_PATH)";
        std::cout << '\n';
        return 0;
    } catch (const std::exception& error) {
        tb_free(); std::cerr << error.what() << '\n'; return 1;
    }
}
