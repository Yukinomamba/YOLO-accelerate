// SPDX-License-Identifier: Apache-2.0
// Adapted from adamgallas module_conv_kernel_1x2{,x8,x8x4}.v, revision 6ba312bd.
// Modified: 8 input x 16 output channels, temporal kernel taps, full-width sums,
// and explicit valid/last pipeline instead of the upstream fixed-cycle controls.
// Module: adam_mac128
// Description: 128 signed INT8 products per input beat; 16 INT32 dot products.
module adam_mac128 (
    input  logic clk,
    input  logic rst,
    input  logic in_valid,
    input  logic in_last,
    input  logic [63:0] in_activation,
    input  logic [1023:0] in_weight,
    output logic out_valid,
    output logic out_last,
    output logic [511:0] out_dot
);
    timeunit 1ns;
    timeprecision 1ps;
    logic [4:0] valid_q, last_q;
    logic signed [15:0] product [16][8];

    for (genvar oc_pair = 0; oc_pair < 8; oc_pair++) begin : g_output_pair
        for (genvar ic = 0; ic < 8; ic++) begin : g_input_channel
            adam_mul_pair u_mul_pair (
                .clk,
                .a(in_weight[((oc_pair*2)*8+ic)*8 +: 8]),
                .b(in_weight[((oc_pair*2+1)*8+ic)*8 +: 8]),
                .c(in_activation[ic*8 +: 8]),
                .ac(product[oc_pair*2][ic]),
                .bc(product[oc_pair*2+1][ic])
            );
        end
    end

    for (genvar oc = 0; oc < 16; oc++) begin : g_dot
        logic signed [16:0] sum2 [4];
        logic signed [17:0] sum4 [2];
        logic signed [18:0] sum8;
        for (genvar j = 0; j < 4; j++) begin : g_sum2
            assign sum2[j] = 17'(product[oc][j*2]) + 17'(product[oc][j*2+1]);
        end
        for (genvar j = 0; j < 2; j++) begin : g_sum4
            assign sum4[j] = 18'(sum2[j*2]) + 18'(sum2[j*2+1]);
        end
        assign sum8 = 19'(sum4[0]) + 19'(sum4[1]);
        always_ff @(posedge clk) begin
            out_dot[oc*32 +: 32] <= 32'(sum8);
        end
    end

    // 乘法四拍，求和一拍；无效拍可以流过数据寄存器，但不能进入累加器。
    always_ff @(posedge clk) begin
        if (rst) begin
            valid_q <= '0;
            last_q <= '0;
        end else begin
            valid_q <= {valid_q[3:0], in_valid};
            last_q <= {last_q[3:0], in_last && in_valid};
        end
    end
    assign out_valid = valid_q[4];
    assign out_last = last_q[4] && valid_q[4];
endmodule
