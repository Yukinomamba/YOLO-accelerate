// Module: tb_adam_primitives
// Description: Direct upstream-versus-port arithmetic/RAM harness for Verilator.
module tb_adam_primitives (
    input logic clk,
    input logic signed [7:0] a, b, c,
    output logic signed [15:0] original_ac, original_bc, port_ac, port_bc,
    input logic ram_we,
    input logic ram_re,
    input logic [3:0] ram_wa, ram_ra,
    input logic [15:0] ram_wdata,
    output logic [15:0] original_rdata, port_rdata
);
    timeunit 1ns;
    timeprecision 1ps;
    cal_mult_int8_x2 u_original (.clk, .a, .b, .c, .ac(original_ac), .bc(original_bc));
    adam_mul_pair u_port (.clk, .a, .b, .c, .ac(port_ac), .bc(port_bc));
    com_simple_dual_port_ram #(.WIDTH(16), .DEPTH(16), .ADDR_BIT(4)) u_original_ram (
        .clk, .we_a(ram_we), .en_a(1'b1), .addr_a(ram_wa), .di_a(ram_wdata),
        .addr_b(ram_ra), .dout_b(original_rdata)
    );
    adam_sdp_ram #(.WIDTH(16), .DEPTH(16), .ADDR_W(4)) u_port_ram (
        .clk, .wr_en(ram_we), .wr_addr(ram_wa), .wr_data(ram_wdata),
        .rd_en(ram_re), .rd_addr(ram_ra), .rd_data(port_rdata)
    );
endmodule
