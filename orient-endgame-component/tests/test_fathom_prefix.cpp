// Exact length hints and complete scalar-decoder comparison; validation only.
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <vector>
#include "../third_party/fathom/src/tbprobe.c"
#undef min
#undef max
#include "fathom_scalar_decode_reference.hpp"

#ifdef DECOMP64
using Code = std::uint64_t;
#else
using Code = std::uint32_t;
#endif
constexpr unsigned WordBits = sizeof(Code) * 8;
struct LegacyPairsData {
    std::uint8_t *indexTable; std::uint16_t *sizeTable;
    std::uint8_t *data; std::uint16_t *offset;
    std::uint8_t *symLen, *symPat;
    std::uint8_t blockSize, idxBits, minLen, constValue[2];
    std::uint64_t base[1];
};
static_assert(sizeof(PairsData) == sizeof(LegacyPairsData) + 256);
static_assert(sizeof(((PairsData*)nullptr)->prefixLen) == 256);
void require(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}
unsigned scalar_length(const PairsData *d, Code code) {
    unsigned index = 0;
    while (code < d->base[index]) ++index;
    return d->minLen + index;
}
unsigned hint_length(const PairsData *d, Code code) {
    const auto hint = d->prefixLen[code >> (WordBits - 8)];
    return hint ? hint : scalar_length(d, code);
}
PairsData *allocate_pairs(unsigned count) {
    auto *d = static_cast<PairsData*>(std::calloc(1, sizeof(PairsData) + count * sizeof(std::uint64_t)));
    require(d != nullptr, "allocation failed"); return d;
}
std::uint64_t tested_codes = 0, tested_decodes = 0;
void check_code(const PairsData *d, Code code) {
    require(hint_length(d, code) == scalar_length(d, code), "prefix length differs from scalar");
    ++tested_codes;
}
void check_thresholds(PairsData *d, unsigned count, std::mt19937_64& random) {
    init_prefix_lengths(d);
    for (unsigned prefix = 0; prefix < 256; ++prefix) {
        const Code low = Code(prefix) << (WordBits - 8);
        const Code high = low | (std::numeric_limits<Code>::max() >> 8);
        check_code(d, low); check_code(d, high);
        if (low) check_code(d, Code(low - 1));
        if (high < std::numeric_limits<Code>::max()) check_code(d, Code(high + 1));
        const auto lower = scalar_length(d, low), upper = scalar_length(d, high);
        require(d->prefixLen[prefix] == (lower == upper ? lower : 0), "incorrect endpoint agreement");
    }
    for (unsigned index = 0; index < count; ++index) {
        const Code boundary = Code(d->base[index]);
        check_code(d, boundary);
        if (boundary) check_code(d, Code(boundary - 1));
        if (boundary < std::numeric_limits<Code>::max()) check_code(d, Code(boundary + 1));
    }
    for (unsigned n = 0; n < 2000; ++n) check_code(d, Code(random()));
}
void length_properties(std::mt19937_64& random) {
    for (unsigned trial = 0; trial < 256; ++trial) {
        const unsigned count = 1 + unsigned(random() % 24);
        const unsigned min_length = 1 + unsigned(random() % (WordBits - count));
        auto *d = allocate_pairs(count); d->minLen = std::uint8_t(min_length);
        std::vector<Code> thresholds(count);
        for (auto& n : thresholds) n = Code(random());
        std::sort(thresholds.begin(), thresholds.end(), std::greater<Code>());
        thresholds.back() = 0;
        for (unsigned i = 0; i < count; ++i) d->base[i] = thresholds[i];
        check_thresholds(d, count, random); std::free(d);
    }
    // Ambiguous intervals must fall back, including both extreme prefixes.
    for (Code threshold : {Code(1), Code((Code(1) << (WordBits - 1)) + 1), std::numeric_limits<Code>::max()}) {
        auto *d = allocate_pairs(2); d->minLen = 1; d->base[0] = threshold; d->base[1] = 0;
        check_thresholds(d, 2, random);
        const auto prefix = threshold >> (WordBits - 8);
        require(d->prefixLen[prefix] == 0, "ambiguous prefix should fall back");
        std::free(d);
    }
}
void put16(std::vector<std::uint8_t>& bytes, unsigned at, unsigned value) {
    bytes[at] = std::uint8_t(value); bytes[at + 1] = std::uint8_t(value >> 8);
}
void scalar_decoder_properties(std::mt19937_64& random) {
    // Complete comb code: lengths 1..L-1 once, length L twice. This creates
    // both cached prefixes and ambiguous prefixes when L exceeds eight.
    for (const auto [shortest, longest] : {std::pair{1u,1u}, {1u,2u}, {1u,8u}, {1u,9u},
                                           {1u,12u}, {3u,3u}, {3u,12u}, {5u,9u}}) {
        const bool uniform = shortest == longest;
        const unsigned length_count = longest - shortest + 1;
        const unsigned symbols = uniform ? (1u << shortest) : (1u << shortest) + longest - shortest;
        std::vector<std::uint8_t> metadata(12 + 2 * length_count + 3 * symbols + (symbols & 1));
        metadata[1] = 9; metadata[2] = 8; metadata[4] = 1;
        metadata[8] = std::uint8_t(longest); metadata[9] = std::uint8_t(shortest);
        for (unsigned length = shortest; length <= longest; ++length)
            put16(metadata, 10 + 2 * (length - shortest), length == longest ? 0 : longest - length + 1);
        put16(metadata, 10 + 2 * length_count, symbols);
        for (unsigned symbol = 0; symbol < symbols; ++symbol) {
            const auto at = 12 + 2 * length_count + 3 * symbol;
            metadata[at] = std::uint8_t(symbol * 13 + 7);
            metadata[at + 1] = 0xf0; metadata[at + 2] = 0xff;
        }
        auto *cursor = metadata.data(); std::size_t sizes[3]{}; std::uint8_t flags{};
        auto *d = setup_pairs(&cursor, 128, sizes, &flags, WDL);
        require(cursor == metadata.data() + metadata.size(), "metadata cursor differs");
        require(sizes[0] == 6 && sizes[1] == 2 && sizes[2] == 512, "wrong synthetic layout");
        alignas(8) std::array<std::uint64_t, 128> storage{};
        std::array<std::uint8_t, 6> indices{0,0,0,0,128,0};
        std::array<std::uint16_t, 1> block_sizes{127};
        d->data = reinterpret_cast<std::uint8_t*>(storage.data());
        d->indexTable = indices.data(); d->sizeTable = block_sizes.data();
        if (longest > 9) require(d->prefixLen[0] == 0, "long comb should exercise fallback");
        for (unsigned trial = 0; trial < 64; ++trial) {
            storage.fill(0); unsigned bit = 0; std::array<unsigned, 128> expected{};
            for (auto& symbol : expected) {
                symbol = unsigned(random() % symbols);
                const unsigned short_start = longest - shortest + 1;
                const unsigned length = uniform ? shortest : symbol < 2 ? longest
                    : symbol < short_start ? longest - symbol + 1 : shortest;
                const unsigned codeword = uniform ? symbol : symbol < 2 ? symbol
                    : symbol < short_start ? 1u : symbol - short_start + 1;
                for (unsigned i = 0; i < length; ++i, ++bit) {
                    const bool one = ((codeword >> (length - 1 - i)) & 1u) != 0;
                    if (one) d->data[bit / 8] |= std::uint8_t(1u << (7 - bit % 8));
                }
            }
            for (unsigned index = 0; index < expected.size(); ++index) {
                const auto actual = decompress_pairs(d, index);
                const auto reference = scalar_decompress_pairs(d, index);
                require(actual == reference, "decoded leaf pointer differs from unchanged scalar decoder");
                require(actual[0] == std::uint8_t(expected[index] * 13 + 7), "decoded symbol differs from encoded stream");
                ++tested_decodes;
            }
        }
        std::free(d);
    }
    std::array<std::uint8_t, 2> constant{0x80,4};
    auto *cursor = constant.data(); std::size_t sizes[3]{}; std::uint8_t flags{};
    auto *d = setup_pairs(&cursor, 1, sizes, &flags, WDL);
    for (unsigned index : {0u,1u,65535u})
        require(decompress_pairs(d,index) == scalar_decompress_pairs(d,index) && decompress_pairs(d,index)[0] == 4,
                "constant decoder changed");
    std::free(d);
}
int main() {
    try {
        std::mt19937_64 random(20261028);
        length_properties(random); scalar_decoder_properties(random);
        std::cout << "{\"word_bits\":" << WordBits << ",\"length_cases\":" << tested_codes
                  << ",\"scalar_decoder_cases\":" << tested_decodes << ",\"extra_pair_bytes\":256}\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
