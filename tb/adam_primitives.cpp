#include "Vtb_adam_primitives.h"
#include "verilated.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>

static void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

int main(int argc, char** argv) {
    try {
        VerilatedContext context;
        context.threads(1);
        context.commandArgs(argc, argv);
        Vtb_adam_primitives d{&context};
        auto tick = [&]() { d.clk = 0; d.eval(); d.clk = 1; d.eval(); };
        std::array<std::array<int, 2>, 4> expected{};
        uint64_t submitted = 0, checked = 0;
        constexpr uint64_t count = 256ULL * 256 * 256;
        d.ram_we = 0; d.ram_re = 0;
        // Exhaust all three signed INT8 operands, including the upstream borrow correction.
        for (uint64_t index = 0; index < count + 3; ++index) {
            int a = int((index >> 16) & 255) - 128;
            int b = int((index >> 8) & 255) - 128;
            int c = int(index & 255) - 128;
            expected[index % 4] = {a*c, b*c};
            d.a = uint8_t(a); d.b = uint8_t(b); d.c = uint8_t(c);
            tick();
            if (index < count) ++submitted;
            if (index >= 3) {
                const auto ref = expected[(index-3) % 4];
                check(int16_t(d.original_ac) == ref[0] && int16_t(d.original_bc) == ref[1],
                      "upstream product differs from integer reference");
                check(d.port_ac == d.original_ac && d.port_bc == d.original_bc,
                      "ported product/latency differs from upstream");
                ++checked;
            }
        }
        check(submitted == count && checked == count, "arithmetic count");
        std::array<uint16_t, 16> memory{};
        for (unsigned i = 0; i < 16; ++i) {
            d.ram_we = 1; d.ram_wa = i; d.ram_wdata = memory[i] = uint16_t(i*977 + 123);
            tick();
        }
        uint16_t held = 0;
        unsigned ram_checked = 0;
        for (unsigned i = 0; i < 1024; ++i) {
            d.ram_ra = (i*5) % 16;
            d.ram_wa = i % 16;
            d.ram_we = (i % 3) != 0;
            d.ram_re = (i % 7) != 0 || i == 0;
            d.ram_wdata = uint16_t(i*571 + 43);
            const uint16_t old = memory[d.ram_ra];
            if (d.ram_re) held = old;
            if (d.ram_we) memory[d.ram_wa] = d.ram_wdata;
            tick();
            check(d.original_rdata == old, "upstream RAM read-first mismatch");
            check(d.port_rdata == held, "portable RAM collision/enable mismatch");
            ++ram_checked;
        }
        std::cout << "PASS adam primitives: " << checked << " exhaustive INT8 triples, "
                  << ram_checked << " RAM checks; latency=4 edges\n";
        d.final();
    } catch (const std::exception& error) {
        std::cerr << "FAIL " << error.what() << '\n';
        return 1;
    }
}
