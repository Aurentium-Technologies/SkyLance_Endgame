#include "orient/nnue.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <filesystem>
#include <fstream>
#include <stdexcept>

namespace orient {
namespace {
constexpr std::array<char, 8> Magic{'O','R','I','E','N','T','N','1'};

std::uint32_t read_unsigned(std::istream& input, int bytes) {
    std::uint32_t value = 0;
    for (int i = 0; i < bytes; ++i) {
        int c = input.get();
        if (c == std::char_traits<char>::eof()) throw std::invalid_argument("Truncated Orient network");
        value |= std::uint32_t(static_cast<unsigned char>(c)) << (8 * i);
    }
    return value;
}
void write_unsigned(std::ostream& output, std::uint32_t value, int bytes) {
    for (int i = 0; i < bytes; ++i) output.put(char((value >> (8 * i)) & 255));
}
std::int16_t read_short(std::istream& input) {
    return std::bit_cast<std::int16_t>(std::uint16_t(read_unsigned(input, 2)));
}
std::int32_t read_int(std::istream& input) {
    return std::bit_cast<std::int32_t>(read_unsigned(input, 4));
}
}

int NeuralNetwork::feature(int p, int square, Color perspective) {
    const int relative_color = color_of(p) == perspective ? 0 : 1;
    const int oriented_square = perspective == White ? square : square ^ 56;
    return (relative_color * 6 + int(type_of(p)) - 1) * 64 + oriented_square;
}

void NeuralNetwork::validate() const {
    // At most 32 board pieces are accumulated. Keep malformed biases well away
    // from int32 overflow; later dense layers use int64 intermediate sums.
    for (auto bias : first_bias)
        if (bias < -(1 << 20) || bias > (1 << 20))
            throw std::invalid_argument("Orient network first-layer bias outside bounds");
}

std::shared_ptr<NeuralNetwork> NeuralNetwork::load(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::invalid_argument("Cannot open Orient network: " + path);
    std::array<char, 8> magic{};
    input.read(magic.data(), magic.size());
    if (magic != Magic) throw std::invalid_argument("Not an Orient ORIENTN1 network");
    for (auto expected : {1u, std::uint32_t(Features), std::uint32_t(First),
                          std::uint32_t(Hidden), std::uint32_t(ActivationScale)})
        if (read_unsigned(input, 4) != expected) throw std::invalid_argument("Unsupported Orient network architecture");
    auto net = std::make_shared<NeuralNetwork>();
    for (auto& value : net->first_bias) value = read_int(input);
    for (auto& row : net->first_weights) for (auto& value : row) value = read_short(input);
    for (auto& value : net->second_bias) value = read_int(input);
    for (auto& row : net->second_weights) for (auto& value : row) value = read_short(input);
    for (auto& value : net->output_weights) value = read_short(input);
    net->output_bias = read_int(input);
    if (input.peek() != std::char_traits<char>::eof()) throw std::invalid_argument("Trailing bytes in Orient network");
    net->validate();
    return net;
}

void NeuralNetwork::save(const std::string& path) const {
    validate();
    if (std::filesystem::exists(path)) throw std::invalid_argument("Refusing to overwrite Orient network");
    std::ofstream output(path, std::ios::binary);
    if (!output) throw std::invalid_argument("Cannot create Orient network: " + path);
    output.write(Magic.data(), Magic.size());
    for (auto value : {1u, std::uint32_t(Features), std::uint32_t(First),
                       std::uint32_t(Hidden), std::uint32_t(ActivationScale)}) write_unsigned(output, value, 4);
    for (auto value : first_bias) write_unsigned(output, std::bit_cast<std::uint32_t>(value), 4);
    for (const auto& row : first_weights) for (auto value : row) write_unsigned(output, std::bit_cast<std::uint16_t>(value), 2);
    for (auto value : second_bias) write_unsigned(output, std::bit_cast<std::uint32_t>(value), 4);
    for (const auto& row : second_weights) for (auto value : row) write_unsigned(output, std::bit_cast<std::uint16_t>(value), 2);
    for (auto value : output_weights) write_unsigned(output, std::bit_cast<std::uint16_t>(value), 2);
    write_unsigned(output, std::bit_cast<std::uint32_t>(output_bias), 4);
    if (!output) throw std::runtime_error("Failed writing Orient network");
}

void NeuralNetwork::change(Accumulator& accumulator, int p, int square, int sign) const {
    for (Color perspective : {White, Black}) {
        const auto& row = first_weights[feature(p, square, perspective)];
        for (int i = 0; i < First; ++i) accumulator.values[perspective][i] += sign * row[i];
    }
}

NeuralNetwork::Accumulator NeuralNetwork::rebuild(const Position& position) const {
    Accumulator result;
    result.values[White] = result.values[Black] = first_bias;
    for (int square = 0; square < 64; ++square)
        if (position.board[square]) change(result, position.board[square], square, 1);
    return result;
}

NeuralNetwork::Accumulator NeuralNetwork::update(const Accumulator& parent, const Position& after,
                                                Move move, const Undo& undo) const {
    Accumulator result = parent;
    const Color us = opposite(after.side);
    const int moving = move.promotion() == Empty ? after.board[move.to()] : piece(us, Pawn);
    change(result, moving, move.from(), -1);
    change(result, after.board[move.to()], move.to(), 1);
    if (undo.captured) change(result, undo.captured, undo.capture_square, -1);
    if (move.has(Move::Castle)) {
        const int rook_from = move.to() > move.from() ? move.from() + 3 : move.from() - 4;
        const int rook_to = move.to() > move.from() ? move.from() + 1 : move.from() - 1;
        change(result, piece(us, Rook), rook_from, -1);
        change(result, piece(us, Rook), rook_to, 1);
    }
    return result;
}

int NeuralNetwork::evaluate(const Accumulator& accumulator, Color side) const {
    std::array<int, 2 * First> input{};
    for (int i = 0; i < First; ++i) {
        input[i] = std::clamp(accumulator.values[side][i], 0, ActivationScale);
        input[First + i] = std::clamp(accumulator.values[opposite(side)][i], 0, ActivationScale);
    }
    std::int64_t result = output_bias;
    for (int h = 0; h < Hidden; ++h) {
        std::int64_t sum = second_bias[h];
        for (int i = 0; i < 2 * First; ++i) sum += std::int64_t(input[i]) * second_weights[h][i];
        const auto activation = std::clamp<std::int64_t>(sum / SecondWeightScale, 0, ActivationScale);
        result += activation * output_weights[h];
    }
    return int(std::clamp<std::int64_t>(result / ActivationScale, -20000, 20000));
}

int NeuralNetwork::evaluate(const Position& position) const {
    return evaluate(rebuild(position), position.side);
}
} // namespace orient
