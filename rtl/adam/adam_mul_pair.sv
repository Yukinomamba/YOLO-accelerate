// SPDX-License-Identifier: Apache-2.0
// Derived from adamgallas cal_mul_int8_x2{,_dsp}.v, revision 6ba312bd.
// Modified: replace the 27x18 packed product and borrow correction with two
// signed 8x8 products; preserve the four-edge input-to-output latency.
// Module: adam_mul_pair
// Description: Two weights share one activation, as in the upstream kernel.
module adam_mul_pair (
    input  logic clk,
    input  logic signed [7:0] a,
    input  logic signed [7:0] b,
    input  logic signed [7:0] c,
    output logic signed [15:0] ac,
    output logic signed [15:0] bc
);
    timeunit 1ns;
    timeprecision 1ps;
    logic signed [7:0] a_q0, b_q0, c_q0;
    logic signed [7:0] a_q1, b_q1, c_q1;
    logic signed [15:0] ac_q2, bc_q2;

    // 数据寄存器不复位；外层 valid 流水负责复位和清空，便于映射 APM。
    always_ff @(posedge clk) begin
        a_q0 <= a;
        b_q0 <= b;
        c_q0 <= c;
        a_q1 <= a_q0;
        b_q1 <= b_q0;
        c_q1 <= c_q0;
        ac_q2 <= a_q1 * c_q1;
        bc_q2 <= b_q1 * c_q1;
        ac <= ac_q2;
        bc <= bc_q2;
    end
endmodule
