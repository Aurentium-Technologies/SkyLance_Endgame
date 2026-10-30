// Compile this translation unit without orient_core. The local reader fork is
// included once so every table mapping can fail deterministically at its OS
// boundary, without changing its installed API or relying on actual exhaustion.
#include <cerrno>
#include <cstdlib>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/mman.h>

namespace {
unsigned failed_mappings = 0;
void* test_failed_mmap(void*, std::size_t, int, int, int, off_t) {
    ++failed_mappings;
    errno = ENOMEM;
    return MAP_FAILED;
}
std::size_t descriptor_count() {
    std::size_t count = 0;
    for ([[maybe_unused]] const auto& entry : std::filesystem::directory_iterator("/proc/self/fd")) ++count;
    return count;
}
}

#define mmap test_failed_mmap
#include "../third_party/fathom/src/tbprobe.c"
#undef mmap

int main(int argc, char** argv) {
    const char* path = argc > 1 ? argv[1] : std::getenv("ORIENT_SYZYGY_PATH");
    if (!path || !*path) { std::cout << "Set ORIENT_SYZYGY_PATH for mapping fault injection\n"; return 77; }
    try {
        // White Ka1,Qd1 versus black Kg8. Without mapping failure this is a
        // definite win; failure must be propagated as unknown, never a draw.
        constexpr std::uint64_t white = 9, black = std::uint64_t{1} << 62;
        constexpr std::uint64_t kings = 1 | black, queens = 8;
        for (int attempt = 0; attempt < 8; ++attempt) {
            if (!tb_init(path) || TB_LARGEST != 5) throw std::runtime_error("complete collection required");
            const auto before = descriptor_count();
            const auto previous_faults = failed_mappings;
            const auto result = tb_probe_wdl(white, black, kings, queens, 0, 0, 0, 0,
                                             0, 0, 0, true);
            if (result != TB_RESULT_FAILED || failed_mappings != previous_faults + 1)
                throw std::runtime_error("mapping failure did not propagate as an unavailable probe");
            if (descriptor_count() != before) throw std::runtime_error("mapping failure leaked a descriptor");
            tb_free();
        }
        std::cout << "Eight injected mapping failures returned unavailable without exit or descriptor leak\n";
        return 0;
    } catch (const std::exception& error) {
        tb_free(); std::cerr << error.what() << '\n'; return 1;
    }
}
