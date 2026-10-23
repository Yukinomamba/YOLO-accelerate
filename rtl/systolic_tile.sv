// Module: systolic_tile
// Description: Parameterized INT8 GEMM tile with explicit skewed input steps.
module systolic_tile #(
    parameter int ROWS = 4,
    parameter int COLS = 4
) (
    input  logic clk,
    input  logic rst,
    input  logic cmd_valid,
    output logic cmd_ready,
    input  logic [15:0] cmd_k,
    input  logic in_valid,
    output logic in_ready,
    input  logic signed [7:0] a_left [ROWS],
    input  logic signed [7:0] b_top [COLS],
    input  logic [ROWS-1:0] a_valid,
    input  logic [COLS-1:0] b_valid,
    output logic out_valid,
    input  logic out_ready,
    output logic signed [31:0] result [ROWS][COLS]
);
    timeunit 1ns;
    timeprecision 1ps;
    typedef enum logic [1:0] {IDLE, RUN, RESULT} state_e;
    state_e state_q;
    logic [31:0] steps_left_q;
    logic cmd_fire, in_fire, out_fire;
    logic signed [7:0] a_link [ROWS][COLS+1];
    logic signed [7:0] b_link [ROWS+1][COLS];
    logic av_link [ROWS][COLS+1];
    logic bv_link [ROWS+1][COLS];

    // cmd_k=0 是非法描述符，不接收；一条命令独占阵列至结果被消费。
    assign cmd_ready = !rst && state_q == IDLE && cmd_k != 0;
    assign in_ready = !rst && state_q == RUN;
    assign out_valid = !rst && state_q == RESULT;
    assign cmd_fire = cmd_valid && cmd_ready;
    assign in_fire = in_valid && in_ready;
    assign out_fire = out_valid && out_ready;

    // 第 t 个被接收的步中，左侧第 r 行送 A[r,t-r]，顶部第 c 列送 B[t-c,c]。
    // 越界 lane 的 valid=0；尾部排空也必须提交 in_valid，停顿不算一步。
    always_ff @(posedge clk) begin
        if (rst) begin
            state_q <= IDLE;
            steps_left_q <= '0;
        end else begin
            unique case (state_q)
                IDLE: begin
                    if (cmd_fire) begin
                        steps_left_q <= {16'b0, cmd_k} + 32'(ROWS + COLS - 2);
                        state_q <= RUN;
                    end
                end
                RUN: begin
                    if (in_fire) begin
                        steps_left_q <= steps_left_q - 1'b1;
                        if (steps_left_q == 1)
                            state_q <= RESULT;
                    end
                end
                RESULT: begin
                    if (out_fire)
                        state_q <= IDLE;
                end
                default: state_q <= IDLE;
            endcase
        end
    end

    for (genvar r = 0; r < ROWS; r++) begin : g_rows
        assign a_link[r][0] = a_left[r];
        assign av_link[r][0] = a_valid[r];
        for (genvar c = 0; c < COLS; c++) begin : g_cols
            systolic_pe u_pe (
                .clk(clk), .rst(rst), .clear(cmd_fire), .advance(in_fire),
                .a_in(a_link[r][c]), .b_in(b_link[r][c]),
                .a_valid_in(av_link[r][c]), .b_valid_in(bv_link[r][c]),
                .a_out(a_link[r][c+1]), .b_out(b_link[r+1][c]),
                .a_valid_out(av_link[r][c+1]), .b_valid_out(bv_link[r+1][c]),
                .sum(result[r][c])
            );
        end
    end
    for (genvar c = 0; c < COLS; c++) begin : g_top
        assign b_link[0][c] = b_top[c];
        assign bv_link[0][c] = b_valid[c];
    end
endmodule
