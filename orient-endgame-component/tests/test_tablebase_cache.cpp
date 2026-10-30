#include "orient/detail/tablebase_cache.hpp"
#include <array>
#include <bit>
#include <cctype>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <unordered_map>

using namespace orient;
using namespace orient::detail;

namespace {
void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
Position position(const std::string& fen) {
    Position result; std::string error;
    if (!result.set_fen(fen, &error)) throw std::runtime_error(error + ": " + fen);
    return result;
}
std::uint64_t identity(const Position& p) {
    const auto result = pack_tablebase_identity(p);
    check(bool(result), "valid position was not encoded");
    check((*result & ~TablebaseIdentityMask) == 0, "identity exceeds 52 bits");
    return *result;
}
std::string placement(const std::array<std::int8_t, 64>& board) {
    constexpr char symbols[] = ".PNBRQK";
    std::string result;
    for (int rank = 7; rank >= 0; --rank) {
        int empty = 0;
        for (int file = 0; file < 8; ++file) {
            const int raw = board[rank * 8 + file];
            if (!raw) { ++empty; continue; }
            if (empty) { result += char('0' + empty); empty = 0; }
            char symbol = symbols[int(type_of(raw))];
            if (raw < 0) symbol = char(std::tolower(static_cast<unsigned char>(symbol)));
            result += symbol;
        }
        if (empty) result += char('0' + empty);
        if (rank) result += '/';
    }
    return result;
}

// Independent unpacker exercises the documented layout without adding a
// decoder or reconstructed chess position to the production cache path.
void roundtrip(const Position& p) {
    const auto value = identity(p);
    std::array<std::int8_t, 64> decoded{};
    const auto wk = unsigned(value & 63), bk = unsigned((value >> 6) & 63);
    decoded[wk] = std::int8_t(piece(White, King));
    decoded[bk] = std::int8_t(piece(Black, King));
    const auto count = unsigned((value >> 20) & 3);
    int previous = -1;
    for (unsigned i = 0; i < 3; ++i) {
        const auto record = unsigned((value >> (22 + 10 * i)) & 1023);
        if (i >= count) { check(record == 0, "unused record was not zero"); continue; }
        const auto square = record & 63;
        const auto type = PieceType((record >> 6) & 7);
        const auto color = Color((record >> 9) & 1);
        check(int(square) > previous && !decoded[square], "record order or square collision");
        previous = int(square);
        check(type >= Pawn && type <= Queen, "record type out of range");
        decoded[square] = std::int8_t(piece(color, type));
    }
    check(decoded == p.board, "piece placement did not round-trip");
    check(Color((value >> 12) & 1) == p.side, "side did not round-trip");
    check(int((value >> 13) & 127) - 1 == p.ep, "en passant did not round-trip");
    check(count + 2 == unsigned(std::popcount(p.occupancy())), "piece count did not round-trip");
    for (int wdl = 0; wdl <= 4; ++wdl) {
        const auto entry = make_tablebase_entry(value, wdl);
        check(sizeof(entry) == 8, "entry is not eight bytes");
        check(tablebase_entry_matches(entry, value), "entry did not match complete identity");
        check(tablebase_entry_wdl(entry) == wdl, "WDL did not round-trip");
        check((entry & ~TablebaseEntryMask) == 0, "reserved entry bits were set");
    }
}

void targeted() {
    auto queen = position("6k1/8/8/8/8/8/8/K2Q4 w - - 0 1");
    const auto q = identity(queen);
    check(!tablebase_entry_matches(0, q) && tablebase_entry_wdl(0) == -1, "empty entry matched");
    check(tablebase_entry_matches(make_tablebase_entry(q, 0), q), "loss code zero treated as empty");
    check(make_tablebase_entry(q, -1) == 0 && make_tablebase_entry(q, 5) == 0, "invalid WDL accepted");
    check(make_tablebase_entry(q | (std::uint64_t{1} << 52), 2) == 0, "oversized identity accepted");
    check(tablebase_entry_wdl(make_tablebase_entry(q, 2) | (std::uint64_t{1} << 63)) == -1,
          "reserved bit corruption accepted");
    check(tablebase_entry_wdl(q | TablebaseValidBit | (std::uint64_t{7} << 52)) == -1,
          "invalid stored outcome accepted");

    for (const char* fen : {
         "6k1/8/8/8/8/8/8/K2R4 w - - 0 1", // type
         "6k1/8/8/8/8/8/8/K2q4 w - - 0 1", // colour (king in check is legal)
         "6k1/8/8/8/8/8/8/K3Q3 w - - 0 1", // square
         "6k1/8/8/8/8/8/8/K2Q4 b - - 0 1", // side
         "7k/8/8/8/8/8/8/K2Q4 w - - 0 1", // black king
         "6k1/8/8/8/8/8/8/1K1Q4 w - - 0 1"}) { // white king
        const auto other = position(fen);
        check(identity(other) != q, "distinct position aliased");
        check(!tablebase_entry_matches(make_tablebase_entry(q, 4), identity(other)), "partial identity matched");
        roundtrip(other);
    }
    auto collision = position("6k1/8/8/8/8/8/8/K2R4 b - - 0 1");
    collision.key = queen.key;
    check(identity(collision) != q, "Zobrist value entered the exact identity");
    check(!tablebase_entry_matches(make_tablebase_entry(q, 4), identity(collision)), "forced slot collision matched");

    const auto ep_none = position("4k3/8/8/3pPp2/8/8/8/4K3 w - - 0 1");
    const auto ep_d = position("4k3/8/8/3pPp2/8/8/8/4K3 w - d6 0 1");
    const auto ep_f = position("4k3/8/8/3pPp2/8/8/8/4K3 w - f6 0 1");
    check(identity(ep_none) != identity(ep_d) && identity(ep_d) != identity(ep_f)
          && identity(ep_none) != identity(ep_f), "EP states aliased");
    for (const auto& p : {ep_none, ep_d, ep_f,
             position("4k3/8/8/8/8/8/8/4K3 w - - 0 1"),
             position("7k/P7/8/8/8/8/8/7K w - - 0 1"),
             position("4k3/8/8/8/8/2N5/2B5/4K3 w - - 0 1")}) roundtrip(p);

    // Position validity is an engine contract, but encoding bounds must still
    // fail safely before any negative square or oversized record can be shifted.
    auto bad = queen; bad.bb[White][King] = 0;
    check(!pack_tablebase_identity(bad), "missing king accepted");
    bad = queen; bad.bb[Black][King] |= bit(60);
    check(!pack_tablebase_identity(bad), "multiple kings accepted");
    bad = queen; bad.ep = 64;
    check(!pack_tablebase_identity(bad), "oversized EP accepted");
    bad.ep = -2; check(!pack_tablebase_identity(bad), "negative invalid EP accepted");
    bad = queen; bad.side = Color(2);
    check(!pack_tablebase_identity(bad), "invalid side accepted");
    bad = queen; bad.board[3] = 7;
    check(!pack_tablebase_identity(bad), "unrepresentable piece type accepted");
    bad = queen; bad.board[3] = -5;
    check(!pack_tablebase_identity(bad), "piece colour and occupancy mismatch accepted");
    check(!pack_tablebase_identity(Position{}), "more than three extra pieces accepted");
}

void generated_roundtrips() {
    std::mt19937_64 random(20261027);
    std::unordered_map<std::uint64_t, std::string> seen;
    std::array<unsigned, 4> counts{};
    for (unsigned n = 0; n < 10000; ++n) {
        const unsigned extras = n % 4;
        bool accepted = false;
        for (unsigned attempt = 0; attempt < 100000 && !accepted; ++attempt) {
            std::array<std::int8_t, 64> board{};
            for (unsigned i = 0; i < extras + 2; ++i) {
                const auto type = i < 2 ? King : PieceType(1 + random() % 5);
                const auto color = i < 2 ? Color(i) : Color(random() % 2);
                unsigned square;
                do { square = unsigned(random() % 64); }
                while (board[square] || (type == Pawn && (square < 8 || square >= 56)));
                board[square] = std::int8_t(piece(color, type));
            }
            const auto fen = placement(board) + (random() & 1 ? " w - - 0 1" : " b - - 0 1");
            Position p;
            if (!p.set_fen(fen)) continue;
            const auto value = identity(p);
            const auto found = seen.find(value);
            if (found != seen.end()) {
                check(found->second == fen, "different generated positions share an identity");
                continue;
            }
            seen.emplace(value, fen);
            roundtrip(p); ++counts[extras]; accepted = true;
        }
        check(accepted, "failed to generate a unique legal fixture");
    }
    check(seen.size() == 10000, "generated fixture coverage incomplete");
    for (unsigned count : counts) check(count == 2500, "piece-count coverage unbalanced");
    std::cout << "10,000 unique rule-validated identities round-trip across two to five pieces\n";
}
}

int main() {
    try {
        targeted(); generated_roundtrips();
        std::cout << "Exact eight-byte entry bounds, WDL payloads and identity distinctions passed\n";
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
