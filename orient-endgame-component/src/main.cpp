#include "orient/chess.hpp"
#include "orient/search.hpp"
#include "orient/nnue.hpp"
#include "orient/tablebases.hpp"

#include <algorithm>
#include <atomic>
#include <charconv>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <exception>
#include <iostream>
#include <limits>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#ifndef ORIENT_VERSION
#define ORIENT_VERSION "development"
#endif

namespace {
using namespace orient;

std::vector<std::string> words(const std::string& text) {
    std::istringstream in(text);
    std::vector<std::string> out;
    for (std::string s; in >> s;) out.push_back(s);
    return out;
}
std::string join(const std::vector<std::string>& parts, std::size_t first, std::size_t last) {
    std::string out;
    for (std::size_t i = first; i < last; ++i) {
        if (!out.empty()) out += ' ';
        out += parts[i];
    }
    return out;
}
std::string lower(std::string text) {
    for (char& c : text) c = char(std::tolower(static_cast<unsigned char>(c)));
    return text;
}
std::int64_t number(const std::string& value, std::int64_t low, std::int64_t high) {
    std::int64_t n = 0;
    auto [end, ec] = std::from_chars(value.data(), value.data() + value.size(), n);
    if (ec != std::errc{} || end != value.data() + value.size() || n < low || n > high)
        throw std::invalid_argument("invalid numeric value: " + value);
    return n;
}
Position load(const std::string& fen) {
    Position p;
    std::string error;
    if (!p.set_fen(fen == "startpos" ? std::string(StartFen) : fen, &error))
        throw std::invalid_argument("invalid FEN: " + error);
    return p;
}
void play(Position& p, const std::string& text) {
    Move move = p.parse_uci(text);
    if (!move) throw std::invalid_argument("illegal move: " + text);
    Undo undo;
    p.make(move, undo);
}

class Uci {
    using Clock = std::chrono::steady_clock;
    Position position_;
    Searcher searcher_;
    SearchOptions options_;
    std::shared_ptr<const NeuralNetwork> network_;
    bool use_network_ = false;
    std::string syzygy_path_;
    int syzygy_limit_ = 5;
    std::size_t syzygy_cache_ = 0;
    std::shared_ptr<Tablebases> tablebases_;
    std::atomic_bool stop_{false};
    std::thread worker_;
    std::mutex output_;
    int overhead_ = 50;
    Clock::duration pending_setup_{};

    void line(const std::string& value) {
        std::lock_guard guard(output_);
        std::cout << value << std::endl;
    }
    void stop_and_join() {
        stop_.store(true, std::memory_order_relaxed);
        stop_.notify_all();
        if (worker_.joinable()) worker_.join();
    }
    void configure_tablebases() {
        // Release the previous cache before allocating its replacement. Search
        // has already joined, so a setting change needs no second full cache.
        searcher_.set_tablebases(nullptr, syzygy_limit_);
        tablebases_.reset();
        tablebases_ = syzygy_path_.empty() ? nullptr
            : std::make_shared<Tablebases>(syzygy_path_, syzygy_cache_);
        searcher_.set_tablebases(tablebases_, syzygy_limit_);
        if (tablebases_ && tablebases_->largest() >= 3)
            line("info string syzygy ready pieces " + std::to_string(std::min(5u, tablebases_->largest()))
                 + " cache_mib " + std::to_string(syzygy_cache_));
        else line("info string syzygy unavailable; using normal search");
    }
    void set_option(const std::vector<std::string>& args) {
        auto name_it = std::find(args.begin() + 1, args.end(), "name");
        if (name_it == args.end()) throw std::invalid_argument("setoption requires name");
        auto value_it = std::find(name_it + 1, args.end(), "value");
        std::string name = join(args, std::size_t(name_it - args.begin() + 1), std::size_t(value_it - args.begin()));
        std::string value = value_it == args.end() ? "" : join(args, std::size_t(value_it - args.begin() + 1), args.size());
        const std::string raw_value = value;
        name = lower(name);
        value = lower(value);
        stop_and_join();
        if (name == "hash") searcher_.resize_hash(std::size_t(number(value, 1, 4096)));
        else if (name == "clear hash") {
            searcher_.clear();
            if (tablebases_) tablebases_->clear_cache();
        }
        else if (name == "syzygypath") {
            syzygy_path_ = raw_value == "<empty>" ? "" : raw_value;
            configure_tablebases();
        } else if (name == "syzygyprobelimit") {
            syzygy_limit_ = int(number(value, 0, 5));
            searcher_.set_tablebases(tablebases_, syzygy_limit_);
        } else if (name == "syzygycache") {
            syzygy_cache_ = std::size_t(number(value, 0, 256));
            configure_tablebases();
        }
        else if (name == "move overhead") overhead_ = int(number(value, 0, 5000));
        else if (name == "threads") (void)number(value, 1, 1);
        else if (name == "ponder" && value != "false")
            throw std::invalid_argument("pondering is not supported");
        else if (name == "evalfile") {
            if (raw_value.empty() || raw_value == "<empty>") {
                network_.reset(); use_network_ = false; searcher_.set_network(nullptr);
            } else {
                auto next = NeuralNetwork::load(raw_value);
                network_ = std::move(next);
                searcher_.set_network(use_network_ ? network_ : nullptr);
            }
        } else if (name == "use nnue") {
            if (value != "true" && value != "false") throw std::invalid_argument("expected true or false");
            if (value == "true" && !network_) throw std::invalid_argument("load an original Orient EvalFile first");
            use_network_ = value == "true";
            searcher_.set_network(use_network_ ? network_ : nullptr);
        }
        else if (name == "pruning") {
            if (value != "true" && value != "false") throw std::invalid_argument("expected true or false");
            options_.null_move = options_.lmr = options_.futility = value == "true";
            searcher_.set_options(options_);
            searcher_.clear();
        } else if (name == "pvs" || name == "aspiration" || name == "see"
                   || name == "null move" || name == "late move reductions" || name == "futility"
                   || name == "fast quiescence" || name == "hash move hints" || name == "direct legal moves") {
            if (value != "true" && value != "false") throw std::invalid_argument("expected true or false");
            const bool enabled = value == "true";
            if (name == "pvs") options_.pvs = enabled;
            else if (name == "aspiration") options_.aspiration = enabled;
            else if (name == "see") options_.see = enabled;
            else if (name == "null move") options_.null_move = enabled;
            else if (name == "late move reductions") options_.lmr = enabled;
            else if (name == "futility") options_.futility = enabled;
            else if (name == "fast quiescence") options_.fast_quiescence = enabled;
            else if (name == "hash move hints") options_.hash_move_hints = enabled;
            else options_.direct_legal = enabled;
            searcher_.set_options(options_);
            searcher_.clear();
        }
    }
    void set_position(const std::vector<std::string>& args) {
        const auto started = Clock::now();
        if (args.size() < 2) throw std::invalid_argument("position requires startpos or fen");
        auto moves_it = std::find(args.begin() + 1, args.end(), "moves");
        std::size_t moves_index = std::size_t(moves_it - args.begin());
        Position next;
        if (args[1] == "startpos") {
            if (moves_index != 2) throw std::invalid_argument("unexpected position token");
        } else if (args[1] == "fen") {
            if (moves_index != 8) throw std::invalid_argument("position fen requires six FEN fields");
            next = load(join(args, 2, moves_index));
        } else throw std::invalid_argument("position requires startpos or fen");
        if (moves_it != args.end()) for (std::size_t i = moves_index + 1; i < args.size(); ++i) play(next, args[i]);
        stop_and_join();
        position_ = std::move(next);
        pending_setup_ += Clock::now() - started;
    }
    void go(const std::vector<std::string>& args) {
        SearchLimits limits;
        limits.received_at = Clock::now() - pending_setup_;
        limits.overhead_ms = overhead_;
        bool has_limit = false;
        for (std::size_t i = 1; i < args.size(); ++i) {
            const auto& t = args[i];
            if (t == "infinite") { limits.infinite = true; has_limit = true; }
            else if (t == "ponder") throw std::invalid_argument("pondering is not supported");
            else if (t == "searchmoves") {
                while (i + 1 < args.size()) {
                    Move m = position_.parse_uci(args[i + 1]);
                    if (!m) break;
                    limits.searchmoves.push_back(m);
                    ++i;
                }
                if (limits.searchmoves.empty()) throw std::invalid_argument("searchmoves requires legal root moves");
            } else if (t == "depth" || t == "nodes" || t == "movetime" || t == "wtime" || t == "btime"
                    || t == "winc" || t == "binc" || t == "movestogo" || t == "mate") {
                if (++i == args.size()) throw std::invalid_argument("missing go limit");
                std::int64_t n = number(args[i], 0, std::numeric_limits<std::int32_t>::max());
                if (t == "depth") limits.depth = int(std::clamp<std::int64_t>(n, 1, MaxPly - 4));
                else if (t == "nodes") { if (!n) throw std::invalid_argument("nodes must be positive"); limits.nodes = std::uint64_t(n); }
                else if (t == "movetime") limits.movetime_ms = std::max<std::int64_t>(1, n);
                else if (t == "wtime") limits.wtime_ms = std::max<std::int64_t>(1, n);
                else if (t == "btime") limits.btime_ms = std::max<std::int64_t>(1, n);
                else if (t == "winc") limits.winc_ms = n;
                else if (t == "binc") limits.binc_ms = n;
                else if (t == "movestogo") limits.movestogo = int(std::max<std::int64_t>(1, n));
                else if (t == "mate") limits.depth = int(std::clamp<std::int64_t>(2 * n, 1, MaxPly - 4));
                has_limit = true;
            }
        }
        if (!has_limit) limits.infinite = true;
        stop_and_join();
        stop_.store(false, std::memory_order_relaxed);
        Position snapshot = position_;
        auto legal = snapshot.legal_moves();
        Move fallback = legal.empty() ? Move{} : legal[0];
        if (!limits.searchmoves.empty()) fallback = limits.searchmoves[0];
        pending_setup_ = Clock::duration::zero();
        worker_ = std::thread([this, snapshot = std::move(snapshot), limits, fallback]() mutable {
            try {
                auto result = searcher_.search(std::move(snapshot), limits, stop_, [this](const SearchInfo& info) {
                    std::ostringstream out;
                    out << "info depth " << info.depth << " seldepth " << info.seldepth << " score ";
                    if (std::abs(info.score) >= MateScore - MaxPly) {
                        int plies = MateScore - std::abs(info.score);
                        out << "mate " << (info.score >= 0 ? 1 : -1) * ((plies + 1) / 2);
                    } else out << "cp " << info.score;
                    out << " nodes " << info.nodes << " time " << info.elapsed_ms
                        << " nps " << info.nodes * 1000 / std::uint64_t(std::max<std::int64_t>(1, info.elapsed_ms))
                        << " tbhits " << info.tablebase_hits << " pv";
                    for (Move m : info.pv) out << ' ' << m.uci();
                    line(out.str());
                });
                // UCI infinite analysis ends only on a stop/quit/new search command,
                // including positions where search has already established a mate/draw.
                if (limits.infinite) stop_.wait(false, std::memory_order_relaxed);
                line("bestmove " + result.best.uci());
            } catch (const std::exception& e) {
                line(std::string("info string search failed: ") + e.what());
                line("bestmove " + fallback.uci());
            }
        });
    }
public:
    ~Uci() { stop_and_join(); }
    void run() {
        for (std::string input; std::getline(std::cin, input);) {
            auto args = words(input);
            if (args.empty()) continue;
            try {
                if (args[0] == "uci") {
                    line("id name SkyLance " ORIENT_VERSION);
                    line("id author Aurentium Technologies");
                    line("option name Hash type spin default 256 min 1 max 4096");
                    line("option name Threads type spin default 1 min 1 max 1");
                    line("option name Move Overhead type spin default 50 min 0 max 5000");
                    line("option name Clear Hash type button");
                    line("option name Ponder type check default false");
                    line("option name Pruning type check default false");
                    line("option name PVS type check default true");
                    line("option name Aspiration type check default true");
                    line("option name SEE type check default true");
                    line("option name Null Move type check default false");
                    line("option name Late Move Reductions type check default false");
                    line("option name Futility type check default false");
                    line("option name Fast Quiescence type check default false");
                    line("option name Hash Move Hints type check default false");
                    line("option name Direct Legal Moves type check default false");
                    line("option name EvalFile type string default <empty>");
                    line("option name Use NNUE type check default false");
                    line("option name SyzygyPath type string default <empty>");
                    line("option name SyzygyProbeLimit type spin default 5 min 0 max 5");
                    line("option name SyzygyCache type spin default 0 min 0 max 256");
                    line("uciok");
                } else if (args[0] == "isready") line("readyok");
                else if (args[0] == "setoption") set_option(args);
                else if (args[0] == "ucinewgame") {
                    stop_and_join(); searcher_.clear(); position_ = Position();
                    pending_setup_ = Clock::duration::zero();
                }
                else if (args[0] == "position") set_position(args);
                else if (args[0] == "go") go(args);
                else if (args[0] == "stop") stop_and_join();
                else if (args[0] == "quit") break;
                else if (args[0] == "d") line("info string " + position_.fen());
            } catch (const std::exception& e) { line(std::string("info string error: ") + e.what()); }
        }
        stop_and_join();
    }
};

int command_line(int argc, char** argv) {
    std::string command = argv[1];
    std::vector<std::string> args;
    for (int i = 0; i < argc; ++i) args.emplace_back(argv[i]);
    if (command == "--help" || command == "help") {
        std::cout << "SkyLance " ORIENT_VERSION " - original C++ chess engine\n"
                  << "No arguments: UCI on stdin/stdout\n"
                  << "  skylance perft DEPTH [FEN]    Count legal leaf positions\n"
                  << "  skylance divide DEPTH [FEN]   Count each root move\n"
                  << "  skylance legal FEN            List legal UCI moves\n"
                  << "  skylance fen FEN [MOVES...]    Play moves and output FEN\n"
                  << "  skylance eval FEN             Side-to-move evaluation in centipawns\n"
                  << "  skylance nnue-eval FILE FEN   Evaluate an Orient-format network\n"
                  << "  skylance bench [DEPTH] [--fast-quiescence] [--hash-move-hints] [--direct-legal]\n"
                  << "FEN may be quoted; use startpos for the initial position.\n";
    } else if (command == "--version") std::cout << "SkyLance " ORIENT_VERSION << '\n';
    else if (command == "perft" || command == "divide") {
        if (argc < 3) throw std::invalid_argument("perft/divide requires depth");
        int depth = int(number(args[2], 0, 10));
        Position p = argc > 3 ? load(join(args, 3, args.size())) : Position();
        if (command == "perft") std::cout << perft(p, depth) << '\n';
        else {
            std::uint64_t total = 0;
            if (depth == 0) { std::cout << "total 1\n"; return 0; }
            for (Move m : p.legal_moves()) {
                Undo undo;
                p.make(m, undo);
                auto count = perft(p, depth - 1);
                p.unmake(m, undo);
                total += count;
                std::cout << m.uci() << ' ' << count << '\n';
            }
            std::cout << "total " << total << '\n';
        }
    } else if (command == "legal" || command == "eval") {
        if (argc < 3) throw std::invalid_argument(command + " requires FEN");
        Position p = load(join(args, 2, args.size()));
        if (command == "eval") std::cout << evaluate(p) << '\n';
        else {
            bool first = true;
            for (Move m : p.legal_moves()) { if (!first) std::cout << ' '; std::cout << m.uci(); first = false; }
            std::cout << '\n';
        }
    } else if (command == "nnue-eval") {
        if (argc < 4) throw std::invalid_argument("nnue-eval requires network file and FEN");
        const auto network = NeuralNetwork::load(args[2]);
        std::cout << network->evaluate(load(join(args, 3, args.size()))) << '\n';
    } else if (command == "fen") {
        if (argc < 3) throw std::invalid_argument("fen requires quoted FEN or startpos");
        Position p = load(args[2]);
        for (std::size_t i = 3; i < args.size(); ++i) play(p, args[i]);
        std::cout << p.fen() << '\n';
    } else if (command == "bench") {
        int depth = 6;
        bool depth_given = false, fast_quiescence = false, hash_move_hints = false, direct_legal = false;
        for (int i = 2; i < argc; ++i) {
            if (args[i] == "--fast-quiescence" && !fast_quiescence) fast_quiescence = true;
            else if (args[i] == "--hash-move-hints" && !hash_move_hints) hash_move_hints = true;
            else if (args[i] == "--direct-legal" && !direct_legal) direct_legal = true;
            else if (!depth_given && !args[i].starts_with("--")) {
                depth = int(number(args[i], 1, 32)); depth_given = true;
            } else throw std::invalid_argument("unexpected bench argument");
        }
        const std::vector<std::string> fens = {std::string(StartFen),
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
            "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"};
        Searcher search(64);
        SearchOptions options; options.fast_quiescence = fast_quiescence;
        options.hash_move_hints = hash_move_hints;
        options.direct_legal = direct_legal;
        search.set_options(options);
        std::atomic_bool stop{false};
        std::uint64_t nodes = 0;
        auto start = std::chrono::steady_clock::now();
        for (const auto& fen : fens) {
            search.clear();
            SearchLimits limits; limits.depth = depth;
            auto result = search.search(load(fen), limits, stop);
            nodes += result.nodes;
            std::cout << "best " << result.best.uci() << " score " << result.score << " nodes " << result.nodes << '\n';
        }
        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count();
        std::cout << "total nodes " << nodes << " time_ms " << ms << " nps " << nodes * 1000 / std::uint64_t(std::max<std::int64_t>(1, ms)) << '\n';
    } else throw std::invalid_argument("unknown command; use --help");
    return 0;
}
} // namespace

int main(int argc, char** argv) {
    try {
        if (argc > 1) return command_line(argc, argv);
        Uci uci;
        uci.run();
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "SkyLance: " << e.what() << '\n';
        return 1;
    }
}
