// SPDX-License-Identifier: Apache-2.0
// Independent division/remainder reference, with 128-bit intermediates.
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>

inline void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}
inline int32_t signed32(uint32_t bits) {
    return bits <= INT32_MAX ? int32_t(bits) : int32_t(int64_t(bits)-(1LL << 32));
}
inline int8_t requant_reference(int32_t value, uint32_t multiplier, unsigned shift) {
    const __int128 product = __int128(value)*multiplier;
    const __int128 magnitude = product < 0 ? -product : product;
    const __int128 denominator = __int128(1) << shift;
    __int128 rounded = magnitude / denominator;
    if ((magnitude % denominator)*2 >= denominator) ++rounded;
    if (product < 0) rounded = -rounded;
    if (rounded > 127) return 127;
    if (rounded < -128) return -128;
    return int8_t(rounded);
}
inline std::array<uint8_t,256> silu_table() {
    std::array<uint8_t,256> table{};
    // Offline demonstration scales; these are not calibrated YOLOX scales.
    for (unsigned i=0; i<256; ++i) {
        const double x = (i < 128 ? int(i) : int(i)-256) / 16.0;
        const long q = std::lround((x/(1.0+std::exp(-x)))*16.0);
        table[i] = uint8_t(std::clamp(q,-128L,127L));
    }
    return table;
}
