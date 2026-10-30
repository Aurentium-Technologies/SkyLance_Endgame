// Batch differential oracle. Build ORIENT_REFERENCE_READER against the pinned,
// unmodified Fathom source and chess.cpp only; the ordinary target uses the fork
// through Orient's adapter. Probe results are validation evidence, never labels.
#include "orient/tablebases.hpp"
#include <algorithm>
#include <array>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#ifdef ORIENT_REFERENCE_READER
#include <tbprobe.h>
#include <bit>
#endif

using namespace orient;
#ifdef ORIENT_REFERENCE_READER
namespace {
bool eligible(const Position& p) {
    return !p.castling && std::popcount(p.occupancy()) <= 5;
}
std::array<std::uint64_t, 8> board(const Position& p) {
    return {p.occupied[White], p.occupied[Black], p.bb[White][King] | p.bb[Black][King],
            p.bb[White][Queen] | p.bb[Black][Queen], p.bb[White][Rook] | p.bb[Black][Rook],
            p.bb[White][Bishop] | p.bb[Black][Bishop], p.bb[White][Knight] | p.bb[Black][Knight],
            p.bb[White][Pawn] | p.bb[Black][Pawn]};
}
Move own(unsigned encoded, Position& position) {
    std::string uci;
    for (unsigned square : {TB_GET_FROM(encoded), TB_GET_TO(encoded)}) {
        uci += char('a' + (square & 7)); uci += char('1' + (square >> 3));
    }
    constexpr char promotions[] = " qrbn";
    if (TB_GET_PROMOTES(encoded) >= std::size(promotions) - 1) return {};
    if (TB_GET_PROMOTES(encoded)) uci += promotions[TB_GET_PROMOTES(encoded)];
    return position.parse_uci(uci);
}
class Provider {
public:
    Provider(const std::string& path, std::size_t) { tb_init(path.c_str()); }
    ~Provider() { tb_free(); }
    WdlProbe probe_wdl(const Position& p) {
        if (!eligible(p) || p.halfmove) return {ProbeStatus::Unsupported, 2};
        const auto b = board(p);
        const unsigned value = tb_probe_wdl(b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
            0, 0, p.ep < 0 ? 0u : unsigned(p.ep), p.side == White);
        if (value == TB_RESULT_FAILED) return {};
        return {ProbeStatus::Success, int(value)};
    }
    RootProbe probe_root(const Position& p) {
        if (!eligible(p) || p.halfmove < 0 || p.halfmove >= 100)
            return {ProbeStatus::Unsupported, 2, 0, {}, {}};
        Position position = p;
        const auto legal = position.legal_moves();
        if (legal.empty()) return {ProbeStatus::Success, p.in_check() ? 0 : 2, 0, {}, {}};
        const auto b = board(p);
        std::array<unsigned, TB_MAX_MOVES> moves;
        moves.fill(TB_RESULT_FAILED);
        const auto value = tb_probe_root(b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
            unsigned(p.halfmove), 0, p.ep < 0 ? 0u : unsigned(p.ep), p.side == White, moves.data());
        if (value == TB_RESULT_FAILED) return {};
        RootProbe result{ProbeStatus::Success, int(TB_GET_WDL(value)), TB_GET_DTZ(value),
                         own(value, position), {}};
        if (!result.suggested) throw std::runtime_error("reference recommended illegal move");
        for (unsigned encoded : moves) {
            if (encoded == TB_RESULT_FAILED) break;
            const Move move = own(encoded, position);
            if (!move) throw std::runtime_error("reference returned illegal alternative");
            result.moves.push_back({move, int(TB_GET_WDL(encoded)), TB_GET_DTZ(encoded)});
        }
        if (result.moves.size() != std::size_t(legal.size()))
            throw std::runtime_error("reference legal-move set differs from Orient");
        return result;
    }
};
}
#else
using Provider = Tablebases;
#endif

int main(int argc, char** argv) {
    try {
        if (argc < 3 || argc > 4)
            throw std::runtime_error("usage: tablebase-probe PATH CACHE_MIB [FENS_FILE]; otherwise FEN lines on stdin");
        const auto mib = std::stoul(argv[2]);
        if (mib > 256) throw std::runtime_error("cache out of range");
        Provider provider(argv[1], mib);
        std::ifstream file;
        if (argc == 4) { file.open(argv[3]); if (!file) throw std::runtime_error("cannot open fixtures"); }
        std::istream& in = argc == 4 ? static_cast<std::istream&>(file) : std::cin;
        for (std::string fen; std::getline(in, fen);) {
            if (fen.empty()) continue;
            Position p; std::string error;
            if (!p.set_fen(fen, &error)) throw std::runtime_error("fixture FEN: " + error);
            const auto wdl = provider.probe_wdl(p);
            auto root = provider.probe_root(p);
#ifndef ORIENT_PRESERVE_TABLEBASE_ORDER
            std::sort(root.moves.begin(), root.moves.end(), [](const auto& a, const auto& b) {
                return a.move.uci() < b.move.uci();
            });
#endif
            std::cout << "{\"status\":" << int(wdl.status) << ",\"wdl\":" << wdl.wdl
                << ",\"root_status\":" << int(root.status) << ",\"root_wdl\":" << root.wdl
                << ",\"dtz\":" << root.dtz << ",\"suggested\":\"" << root.suggested.uci() << "\",\"moves\":[";
            bool first = true;
            for (const auto& move : root.moves) {
                if (!first) std::cout << ',';
                first = false;
                std::cout << "[\"" << move.move.uci() << "\"," << move.wdl << ',' << move.dtz << ']';
            }
            std::cout << "]}\n";
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
