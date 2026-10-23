// SPDX-License-Identifier: Apache-2.0
// Derived from adamgallas com_simple_dual_port_ram.v, revision 6ba312bd.
// Modified: synchronous read enable, no implicit power-up initialization, and
// no Xilinx ram_style attribute. Same-clock same-address reads return old data.
// Module: adam_sdp_ram
// Description: Portable simple dual-port RAM; one write and one registered read.
module adam_sdp_ram #(
    parameter int WIDTH = 64,
    parameter int DEPTH = 1024,
    parameter int ADDR_W = $clog2(DEPTH)
) (
    input  logic clk,
    input  logic wr_en,
    input  logic [ADDR_W-1:0] wr_addr,
    input  logic [WIDTH-1:0] wr_data,
    input  logic rd_en,
    input  logic [ADDR_W-1:0] rd_addr,
    output logic [WIDTH-1:0] rd_data
);
    timeunit 1ns;
    timeprecision 1ps;
    logic [WIDTH-1:0] mem [DEPTH];
    always_ff @(posedge clk) begin
        if (wr_en) mem[wr_addr] <= wr_data;
        if (rd_en) rd_data <= mem[rd_addr];
    end
endmodule
