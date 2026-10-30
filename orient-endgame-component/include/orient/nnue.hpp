#pragma once

#include "orient/chess.hpp"
#include <array>
#include <cstdint>
#include <memory>
#include <string>

namespace orient {

// Orient's own compact network format. No existing engine's network is accepted.
class NeuralNetwork {
public:
    static constexpr int Features = 768;
    static constexpr int First = 128;
    static constexpr int Hidden = 32;
    static constexpr int ActivationScale = 256;
    static constexpr int SecondWeightScale = 64;
    struct Accumulator {
        std::array<std::array<std::int32_t, First>, 2> values{};
        bool operator==(const Accumulator&) const = default;
    };

    std::array<std::int32_t, First> first_bias{};
    std::array<std::array<std::int16_t, First>, Features> first_weights{};
    std::array<std::int32_t, Hidden> second_bias{};
    std::array<std::array<std::int16_t, 2 * First>, Hidden> second_weights{};
    std::array<std::int16_t, Hidden> output_weights{};
    std::int32_t output_bias = 0;

    static int feature(int p, int square, Color perspective);
    static std::shared_ptr<NeuralNetwork> load(const std::string& path);
    void save(const std::string& path) const;
    Accumulator rebuild(const Position& position) const;
    Accumulator update(const Accumulator& parent, const Position& after,
                       Move move, const Undo& undo) const;
    int evaluate(const Accumulator& accumulator, Color side) const;
    int evaluate(const Position& position) const;
private:
    void validate() const;
    void change(Accumulator& accumulator, int p, int square, int sign) const;
};

} // namespace orient
