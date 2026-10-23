// SPDX-License-Identifier: Apache-2.0
// Module: adam_conv128
// Description: Tile sequencer around the ported adamgallas paired-MAC backend.
// New control/layout: 1x1/3x3, stride 1/2, zero padding, channel tails and INT32 bias.
// One command computes all pixels of an input tile for up to 16 output channels.
module adam_conv128 #(
    parameter int MAX_SIDE = 16,
    parameter int MAX_CIN = 768,
    parameter int GROUPS = (MAX_CIN + 7) / 8,
    parameter int ACT_DEPTH = MAX_SIDE * MAX_SIDE * GROUPS,
    parameter int WEIGHT_DEPTH = 9 * GROUPS,
    parameter int ACT_AW = $clog2(ACT_DEPTH),
    parameter int WEIGHT_AW = $clog2(WEIGHT_DEPTH)
) (
    input  logic clk,
    input  logic rst,
    input  logic act_wr_valid,
    output logic act_wr_ready,
    input  logic [ACT_AW-1:0] act_wr_addr,
    input  logic [63:0] act_wr_data,
    input  logic weight_wr_valid,
    output logic weight_wr_ready,
    input  logic [WEIGHT_AW-1:0] weight_wr_addr,
    input  logic [1023:0] weight_wr_data,
    input  logic cmd_valid,
    output logic cmd_ready,
    input  logic [7:0] cmd_width,
    input  logic [7:0] cmd_height,
    input  logic [15:0] cmd_cin,
    input  logic [4:0] cmd_cout,
    input  logic cmd_kernel3,
    input  logic cmd_stride2,
    input  logic cmd_pad,
    input  logic [511:0] cmd_bias,
    output logic cmd_error,
    output logic busy,
    output logic done,
    output logic out_valid,
    input  logic out_ready,
    output logic [511:0] out_data,
    output logic [15:0] out_mask,
    output logic [7:0] out_x,
    output logic [7:0] out_y,
    output logic out_last,
    output logic [31:0] perf_mac_steps,
    output logic [31:0] perf_active_cycles
);
    timeunit 1ns;
    timeprecision 1ps;
    typedef enum logic [2:0] {IDLE, PREPARE, ISSUE, DRAIN, OUTPUT} state_t;
    state_t state_q;
    logic cmd_fire, out_fire, descriptor_ok;
    logic [7:0] width_q, height_q, out_width_q, out_height_q;
    logic [15:0] cin_q, groups_q, group_q;
    logic [4:0] cout_q;
    logic kernel3_q, stride2_q, pad_q;
    logic [1:0] tap_x_q, tap_y_q;
    logic [511:0] bias_q;
    logic [31:0] accumulator_q [16];
    logic [ACT_AW-1:0] act_rd_addr;
    logic [WEIGHT_AW-1:0] weight_rd_addr;
    logic [63:0] act_rd_data, mac_activation;
    logic [1023:0] weight_rd_data, mac_weight;
    logic read_valid_q, read_last_q, read_padding_q;
    logic [7:0] read_mask_q;
    logic issue_last, inside_image;
    logic mac_valid, mac_last;
    logic [511:0] mac_dot;
    int input_x, input_y, kernel_size, proposed_width, proposed_height;

    assign busy = state_q != IDLE;
    // 装载优先于命令。忙时禁止改写缓存，复位期间禁止任何握手。
    // 窄无符号量先补零再转 int；ADS 2025.2 对直接 int'(x) 的扩展与 Verilator 不同。
    assign act_wr_ready = !rst && !busy && int'({1'b0, act_wr_addr}) < ACT_DEPTH;
    assign weight_wr_ready = !rst && !busy && int'({1'b0, weight_wr_addr}) < WEIGHT_DEPTH;
    assign cmd_ready = !rst && !busy && !act_wr_valid && !weight_wr_valid;
    assign cmd_fire = cmd_valid && cmd_ready;
    assign out_valid = !rst && state_q == OUTPUT;
    assign out_fire = out_valid && out_ready;
    assign out_last = out_x == out_width_q - 1'b1 && out_y == out_height_q - 1'b1;

    always_comb begin
        proposed_width = int'({1'b0, cmd_width}) + 2*int'({1'b0, cmd_pad}) - (cmd_kernel3 ? 3 : 1);
        proposed_height = int'({1'b0, cmd_height}) + 2*int'({1'b0, cmd_pad}) - (cmd_kernel3 ? 3 : 1);
        descriptor_ok = cmd_width > 0 && int'({1'b0, cmd_width}) <= MAX_SIDE &&
                        cmd_height > 0 && int'({1'b0, cmd_height}) <= MAX_SIDE &&
                        cmd_cin > 0 && int'({1'b0, cmd_cin}) <= MAX_CIN &&
                        cmd_cout > 0 && cmd_cout <= 16 &&
                        (cmd_kernel3 || !cmd_pad) && proposed_width >= 0 && proposed_height >= 0;
    end

    always_comb begin
        kernel_size = kernel3_q ? 3 : 1;
        input_x = int'({1'b0, out_x}) * (stride2_q ? 2 : 1) + int'({1'b0, tap_x_q}) - int'({1'b0, pad_q});
        input_y = int'({1'b0, out_y}) * (stride2_q ? 2 : 1) + int'({1'b0, tap_y_q}) - int'({1'b0, pad_q});
        inside_image = input_x >= 0 && input_x < int'({1'b0, width_q}) &&
                       input_y >= 0 && input_y < int'({1'b0, height_q});
        act_rd_addr = '0;
        if (inside_image)
            act_rd_addr = ACT_AW'((input_y*int'({1'b0, width_q})+input_x)*int'({1'b0, groups_q})+int'({1'b0, group_q}));
        weight_rd_addr = WEIGHT_AW'((int'({1'b0, tap_y_q})*kernel_size+int'({1'b0, tap_x_q}))*int'({1'b0, groups_q})+int'({1'b0, group_q}));
        issue_last = group_q == groups_q - 1'b1 &&
                     int'({1'b0, tap_x_q}) == kernel_size-1 && int'({1'b0, tap_y_q}) == kernel_size-1;
    end

    adam_sdp_ram #(.WIDTH(64), .DEPTH(ACT_DEPTH), .ADDR_W(ACT_AW)) u_activation_ram (
        .clk, .wr_en(act_wr_valid && act_wr_ready), .wr_addr(act_wr_addr), .wr_data(act_wr_data),
        .rd_en(!rst && state_q == ISSUE && inside_image), .rd_addr(act_rd_addr), .rd_data(act_rd_data)
    );
    adam_sdp_ram #(.WIDTH(1024), .DEPTH(WEIGHT_DEPTH), .ADDR_W(WEIGHT_AW)) u_weight_ram (
        .clk, .wr_en(weight_wr_valid && weight_wr_ready), .wr_addr(weight_wr_addr), .wr_data(weight_wr_data),
        .rd_en(!rst && state_q == ISSUE), .rd_addr(weight_rd_addr), .rd_data(weight_rd_data)
    );

    // SRAM 一拍读延迟的标签；padding 不读输入 RAM，直接向 MAC 送真实的零。
    always_ff @(posedge clk) begin
        if (rst) begin
            read_valid_q <= 1'b0;
            read_last_q <= 1'b0;
            read_padding_q <= 1'b0;
            read_mask_q <= '0;
        end else begin
            read_valid_q <= state_q == ISSUE;
            read_last_q <= state_q == ISSUE && issue_last;
            read_padding_q <= !inside_image;
            for (int lane = 0; lane < 8; lane++)
                read_mask_q[lane] <= int'({1'b0, group_q})*8 + lane < int'({1'b0, cin_q});
        end
    end

    always_comb begin
        mac_activation = '0;
        mac_weight = '0;
        for (int ic = 0; ic < 8; ic++) begin
            if (read_mask_q[ic] && !read_padding_q)
                mac_activation[ic*8 +: 8] = act_rd_data[ic*8 +: 8];
            for (int oc = 0; oc < 16; oc++) begin
                if (oc < int'({1'b0, cout_q}) && read_mask_q[ic])
                    mac_weight[(oc*8+ic)*8 +: 8] = weight_rd_data[(oc*8+ic)*8 +: 8];
            end
        end
    end
    adam_mac128 u_mac (
        .clk, .rst, .in_valid(read_valid_q), .in_last(read_last_q),
        .in_activation(mac_activation), .in_weight(mac_weight),
        .out_valid(mac_valid), .out_last(mac_last), .out_dot(mac_dot)
    );

    // 每个像素独立初始化 bias；所有输入组与 kernel tap 都在 INT32 域累加。
    always_ff @(posedge clk) begin
        if (rst) begin
            out_data <= '0;
            for (int oc = 0; oc < 16; oc++) accumulator_q[oc] <= '0;
        end else if (state_q == PREPARE) begin
            for (int oc = 0; oc < 16; oc++)
                accumulator_q[oc] <= oc < int'({1'b0, cout_q}) ? bias_q[oc*32 +: 32] : 32'b0;
        end else if (mac_valid) begin
            for (int oc = 0; oc < 16; oc++) begin
                accumulator_q[oc] <= accumulator_q[oc] + mac_dot[oc*32 +: 32];
                if (mac_last) out_data[oc*32 +: 32] <= accumulator_q[oc] + mac_dot[oc*32 +: 32];
            end
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            state_q <= IDLE;
            cmd_error <= 1'b0;
            done <= 1'b0;
            width_q <= '0;
            height_q <= '0;
            cin_q <= '0;
            cout_q <= '0;
            groups_q <= '0;
            group_q <= '0;
            kernel3_q <= 1'b0;
            stride2_q <= 1'b0;
            pad_q <= 1'b0;
            tap_x_q <= '0;
            tap_y_q <= '0;
            bias_q <= '0;
            out_width_q <= '0;
            out_height_q <= '0;
            out_x <= '0;
            out_y <= '0;
            out_mask <= '0;
            perf_mac_steps <= '0;
            perf_active_cycles <= '0;
        end else begin
            cmd_error <= 1'b0;
            done <= 1'b0;
            if (busy) perf_active_cycles <= perf_active_cycles + 1'b1;
            unique case (state_q)
                IDLE: begin
                    if (cmd_fire) begin
                        if (!descriptor_ok) begin
                            cmd_error <= 1'b1;
                        end else begin
                            width_q <= cmd_width;
                            height_q <= cmd_height;
                            cin_q <= cmd_cin;
                            cout_q <= cmd_cout;
                            groups_q <= (cmd_cin + 16'd7) >> 3;
                            kernel3_q <= cmd_kernel3;
                            stride2_q <= cmd_stride2;
                            pad_q <= cmd_pad;
                            bias_q <= cmd_bias;
                            out_width_q <= 8'((proposed_width >> int'({1'b0, cmd_stride2})) + 1);
                            out_height_q <= 8'((proposed_height >> int'({1'b0, cmd_stride2})) + 1);
                            out_x <= '0;
                            out_y <= '0;
                            for (int oc = 0; oc < 16; oc++) out_mask[oc] <= oc < int'({1'b0, cmd_cout});
                            perf_mac_steps <= '0;
                            perf_active_cycles <= '0;
                            state_q <= PREPARE;
                        end
                    end
                end
                PREPARE: begin
                    group_q <= '0;
                    tap_x_q <= '0;
                    tap_y_q <= '0;
                    state_q <= ISSUE;
                end
                ISSUE: begin
                    perf_mac_steps <= perf_mac_steps + 1'b1;
                    if (issue_last) begin
                        state_q <= DRAIN;
                    end else if (group_q == groups_q - 1'b1) begin
                        group_q <= '0;
                        if (int'({1'b0, tap_x_q}) == kernel_size-1) begin
                            tap_x_q <= '0;
                            tap_y_q <= tap_y_q + 1'b1;
                        end else begin
                            tap_x_q <= tap_x_q + 1'b1;
                        end
                    end else begin
                        group_q <= group_q + 1'b1;
                    end
                end
                DRAIN: if (mac_valid && mac_last) state_q <= OUTPUT;
                OUTPUT: begin
                    if (out_fire) begin
                        if (out_last) begin
                            done <= 1'b1;
                            state_q <= IDLE;
                        end else begin
                            if (out_x == out_width_q - 1'b1) begin
                                out_x <= '0;
                                out_y <= out_y + 1'b1;
                            end else begin
                                out_x <= out_x + 1'b1;
                            end
                            state_q <= PREPARE;
                        end
                    end
                end
                default: state_q <= IDLE;
            endcase
        end
    end
endmodule
