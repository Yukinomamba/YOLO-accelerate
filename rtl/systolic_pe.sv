// Module: systolic_pe
// Description: Signed INT8 output-stationary MAC with globally stalled links.
module systolic_pe (
    input  logic clk,
    input  logic rst,
    input  logic clear,
    input  logic advance,
    input  logic signed [7:0] a_in,
    input  logic signed [7:0] b_in,
    input  logic a_valid_in,
    input  logic b_valid_in,
    output logic signed [7:0] a_out,
    output logic signed [7:0] b_out,
    output logic a_valid_out,
    output logic b_valid_out,
    output logic signed [31:0] sum
);
    timeunit 1ns;
    timeprecision 1ps;
    logic signed [15:0] product;
    assign product = a_in * b_in;

    // clear 拥有最高同步优先级；停顿时数据、有效位与部分和一同保持。
    always_ff @(posedge clk) begin
        if (rst || clear) begin
            a_out <= '0;
            b_out <= '0;
            a_valid_out <= 1'b0;
            b_valid_out <= 1'b0;
            sum <= '0;
        end else if (advance) begin
            a_out <= a_in;
            b_out <= b_in;
            a_valid_out <= a_valid_in;
            b_valid_out <= b_valid_in;
            if (a_valid_in && b_valid_in)
                sum <= sum + {{16{product[15]}}, product};
        end
    end
endmodule
