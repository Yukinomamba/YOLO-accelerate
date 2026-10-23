/* SPDX-License-Identifier: Apache-2.0
 * Native Accel_Conv ABI, commit 6ba312bd. No floating point or Xilinx BSP.
 * Transport supplies MMIO writes, contiguous 64-bit streams and completion.
 */
#ifndef ADAM_UPSTREAM_ABI_H
#define ADAM_UPSTREAM_ABI_H
#include <stdint.h>
#include <stddef.h>

enum { ADAM_CTRL=0, ADAM_SCALE=4, ADAM_ZERO=8, ADAM_ADDR=12 };
enum { ADAM_RECV=1, ADAM_SEND=2, ADAM_CONV=16, ADAM_POOL=32,
       ADAM_FIRST=64, ADAM_LAST=128, ADAM_BANK=256, ADAM_TASK=512,
       ADAM_RELU=65536 };
enum { ADAM_IFM=0, ADAM_WEIGHT=1, ADAM_ACTIVATION=2, ADAM_BIAS=3 };

typedef void (*adam_write32_fn)(void *context, unsigned offset, uint32_t value);
/* Caller serializes access and keeps shape/bank/quantization fixed through done.
 * write32 must complete its write response before returning. task_valid clears
 * the upstream sticky done and resets weight/bias load counters.
 */
static inline void adam_begin_task(adam_write32_fn write32, void *context,
                                   uint32_t config, unsigned action) {
    write32(context, ADAM_CTRL, config | action | ADAM_TASK);
    write32(context, ADAM_CTRL, config);
}

static inline uint32_t adam_shape(unsigned rows, unsigned width_sel) {
    return ((uint32_t)rows << 24) | ((uint32_t)width_sel << 10);
}

/* Pixel-major, eight channels in ascending byte order. Pad channel tails in SW. */
static inline uint64_t adam_pack_pixel(const int8_t data[8]) {
    uint64_t word=0;
    for (unsigned c=0;c<8;c++) word |= (uint64_t)(uint8_t)data[c] << (8*c);
    return word;
}

/* OIHW [8][8][3][3] -> input channel, kernel row/column, eight OUTPUT lanes.
 * All 72 words must be sent without bubbles inside each nine-word window.
 * For 1x1, SW sets the other eight kernel taps to zero.
 */
static inline void adam_pack_weights(const int8_t weights[8][8][9], uint64_t words[72]) {
    for (unsigned i=0;i<8;i++) for (unsigned k=0;k<9;k++) {
        uint64_t word=0;
        for (unsigned o=0;o<8;o++) word |= (uint64_t)(uint8_t)weights[o][i][k] << (8*o);
        words[i*9+k]=word;
    }
}

/* Bias is ONE signed 18-bit value per 64-bit stream beat, eight beats/group. */
static inline uint64_t adam_pack_bias(int32_t bias) { return (uint32_t)bias & 0x3ffffu; }
static inline uint32_t adam_quant_config(int16_t scale, unsigned shift) {
    return (uint16_t)scale | ((shift & 15u) << 16);
}
#endif
