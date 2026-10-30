// Original Orient-rule replay and independent game-result checks for the
// bounded endgame experiment. Oracle values are measurement evidence only.
#include "orient/chess.hpp"
#include "orient/tablebases.hpp"

#include <algorithm>
#include <bit>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace orient;

std::string json(const std::string& value) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : value) {
        switch (c) {
        case '"': out << "\\\""; break;
        case '\\': out << "\\\\"; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c) << std::dec;
            else out << char(c);
        }
    }
    out << '"';
    return out.str();
}

std::vector<std::string> fields(const std::string& line) {
    std::vector<std::string> out;
    std::size_t first = 0;
    for (;;) {
        const auto next = line.find('\t', first);
        out.push_back(line.substr(first, next == std::string::npos ? next : next - first));
        if (next == std::string::npos) return out;
        first = next + 1;
    }
}

MoveList checked_legal(Position& p) {
    const auto fen = p.fen(); const auto key = p.key; const auto history = p.history;
    const auto legal = p.legal_moves();
    const auto direct = p.legal_moves_direct();
    if (p.fen() != fen || p.key != key || p.history != history || !p.consistent())
        throw std::runtime_error("reference legal generation changed the position");
    if (legal.size() != direct.size() || !std::equal(legal.begin(), legal.end(), direct.begin()))
        throw std::runtime_error("reference and direct legal lists differ");
    return legal;
}

struct Ending {
    bool terminal = false;
    std::string result = "*", reason;
};
Ending ending(const Position& p, const MoveList& legal) {
    // Match existing Orient semantics: mate precedes any claimable draw.
    if (legal.empty()) {
        if (p.in_check()) return {true, p.side == White ? "0-1" : "1-0", "checkmate"};
        return {true, "1/2-1/2", "stalemate"};
    }
    if (p.insufficient_material()) return {true, "1/2-1/2", "insufficient_material"};
    if (p.halfmove >= 100) return {true, "1/2-1/2", "fifty_move"};
    if (p.repetition_count() >= 3) return {true, "1/2-1/2", "threefold"};
    return {};
}

bool sensitive_history(const Position& p) {
    const auto count = std::min(p.history.size(), std::size_t(std::min(p.halfmove, 100) + 1));
    const auto start = p.history.size() - count;
    for (std::size_t i = start; i < p.history.size(); ++i)
        for (std::size_t j = start; j < i; ++j)
            if (p.history[i] == p.history[j]) return true;
    return false;
}

char letter(PieceType type) {
    constexpr char value[] = " PNBRQK";
    return value[int(type)];
}

std::string san_before(const Position& p, Move move, const MoveList& legal) {
    if (move.has(Move::Castle)) return move.to() > move.from() ? "O-O" : "O-O-O";
    const auto type = type_of(p.board[move.from()]);
    std::string text;
    if (type == Pawn) {
        if (move.capture()) text += char('a' + file_of(move.from()));
    } else {
        text += letter(type);
        bool ambiguous = false, same_file = false, same_rank = false;
        for (auto other : legal) {
            if (other == move || other.to() != move.to() || type_of(p.board[other.from()]) != type) continue;
            ambiguous = true;
            same_file |= file_of(other.from()) == file_of(move.from());
            same_rank |= rank_of(other.from()) == rank_of(move.from());
        }
        if (ambiguous) {
            if (!same_file) text += char('a' + file_of(move.from()));
            else if (!same_rank) text += char('1' + rank_of(move.from()));
            else { text += char('a' + file_of(move.from())); text += char('1' + rank_of(move.from())); }
        }
    }
    if (move.capture()) text += 'x';
    text += char('a' + file_of(move.to())); text += char('1' + rank_of(move.to()));
    if (move.promotion() != Empty) { text += '='; text += letter(move.promotion()); }
    return text;
}

void output(Position& p, const MoveList& legal, const Ending& end,
            const std::vector<std::string>& sans, Tablebases* tables) {
    std::ostringstream out;
    const bool history_sensitive = sensitive_history(p);
    RootProbe probe;
    bool boundary_sensitive = false;
    if (!end.terminal && tables) {
        probe = tables->probe_root(p, legal);
        if (probe.status == ProbeStatus::Success) {
            for (const auto& item : probe.moves) {
                if (item.move.capture() || type_of(p.board[item.move.from()]) == Pawn
                    || item.dtz == 0 || item.dtz + unsigned(p.halfmove) != 100) continue;
                Position child = p; Undo undo; child.make(item.move, undo);
                const auto child_legal = checked_legal(child);
                if (!(child.in_check() && child_legal.empty())) boundary_sensitive = true;
            }
        }
    }
    out << "{\"ok\":true,\"fen\":" << json(p.fen())
        << ",\"side\":" << json(p.side == White ? "white" : "black")
        << ",\"piece_count\":" << std::popcount(p.occupancy())
        << ",\"check\":" << (p.in_check() ? "true" : "false")
        << ",\"halfmove\":" << p.halfmove << ",\"fullmove\":" << p.fullmove
        << ",\"repetition_count\":" << p.repetition_count()
        << ",\"history_sensitive\":" << (history_sensitive ? "true" : "false")
        << ",\"key\":" << json(std::to_string(p.key))
        << ",\"terminal\":" << (end.terminal ? "true" : "false")
        << ",\"result\":" << json(end.result) << ",\"termination\":" << json(end.reason)
        << ",\"last_san\":" << json(sans.empty() ? "" : sans.back()) << ",\"san_moves\":[";
    bool first = true;
    for (const auto& text : sans) { if (!first) out << ','; first = false; out << json(text); }
    out << "],\"legal\":[";
    first = true;
    for (auto move : legal) { if (!first) out << ','; first = false; out << json(move.uci()); }
    out << "],\"oracle\":";
    if (end.terminal) {
        out << "{\"status\":\"terminal\",\"available\":true,\"exact\":true,\"wdl\":"
            << (end.reason == "checkmate" ? 0 : 2) << ",\"dtz\":0,\"dtz_boundary_sensitive\":false,\"suggested\":null,\"moves\":[]}";
    } else if (!tables) {
        out << "{\"status\":\"disabled\",\"available\":false,\"exact\":false,\"wdl\":null,\"dtz\":null,\"dtz_boundary_sensitive\":false,\"suggested\":null,\"moves\":[]}";
    } else {
        const bool success = probe.status == ProbeStatus::Success;
        const auto status = success ? "success" : probe.status == ProbeStatus::Unsupported ? "unsupported" : "unavailable";
        out << "{\"status\":" << json(status) << ",\"available\":" << (success ? "true" : "false")
            << ",\"exact\":" << (success && !history_sensitive && !boundary_sensitive ? "true" : "false")
            << ",\"dtz_boundary_sensitive\":" << (boundary_sensitive ? "true" : "false")
            << ",\"wdl\":";
        if (success) out << probe.wdl; else out << "null";
        out << ",\"dtz\":";
        if (success) out << probe.dtz; else out << "null";
        out << ",\"suggested\":" << (success ? json(probe.suggested.uci()) : "null") << ",\"moves\":[";
        first = true;
        for (const auto& item : probe.moves) {
            if (!first) out << ',';
            first = false;
            out << "{\"uci\":" << json(item.move.uci()) << ",\"wdl\":" << item.wdl << ",\"dtz\":" << item.dtz << '}';
        }
        out << "]}";
    }
    out << "}\n";
    std::cout << out.str() << std::flush;
}

void request(const std::string& line, Tablebases* tables) {
    const auto input = fields(line);
    if (input.size() < 2 || input[0] != "state") throw std::runtime_error("expected state<TAB>FEN<TAB>moves");
    Position position; std::string error;
    if (!position.set_fen(input[1], &error)) throw std::runtime_error("invalid initial FEN: " + error);
    auto legal = checked_legal(position);
    auto end = ending(position, legal);
    std::vector<std::string> sans;
    sans.reserve(input.size() - 2);
    for (std::size_t i = 2; i < input.size(); ++i) {
        if (end.terminal) throw std::runtime_error("move supplied after terminal position: " + end.reason);
        const auto found = std::find_if(legal.begin(), legal.end(), [&](Move m) { return m.uci() == input[i]; });
        if (found == legal.end()) throw std::runtime_error("illegal move: " + input[i]);
        auto san = san_before(position, *found, legal);
        Undo undo; position.make(*found, undo);
        if (!position.consistent()) throw std::runtime_error("inconsistent state after move");
        legal = checked_legal(position);
        end = ending(position, legal);
        if (position.in_check()) san += legal.empty() ? '#' : '+';
        sans.push_back(std::move(san));
    }
    output(position, legal, end, sans, tables);
}
}

int main(int argc, char** argv) {
    try {
        if (argc > 2) throw std::runtime_error("usage: orient-endgame-referee [TABLEPATH|--no-oracle]");
        std::unique_ptr<orient::Tablebases> tables;
        const char* path = argc > 1 ? argv[1] : std::getenv("ORIENT_SYZYGY_PATH");
        if (path && *path && std::string(path) != "--no-oracle") tables = std::make_unique<orient::Tablebases>(path, 0);
        for (std::string line; std::getline(std::cin, line);) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            try { request(line, tables.get()); }
            catch (const std::exception& error) { std::cout << "{\"ok\":false,\"error\":" << json(error.what()) << "}\n" << std::flush; }
        }
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
