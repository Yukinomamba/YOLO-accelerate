// SPDX-License-Identifier: Apache-2.0
// Module: adam_upstream
// Description: Unmodified upstream 576-product engine with its native CSR/AXIS ABI.
// All parameters, arithmetic widths, pipeline stages and task control are upstream.
module adam_upstream
#(
    parameter FM_ADDR_BIT=12,
    parameter WEIGHT_AXI_ADDR_BIT=14,
    parameter WEIGHTBUF_ADDR_BIT=7,
    parameter BIASBUF_ADDR_BIT=7,

    parameter FM_DEPTH=4096,
    parameter WEIGHTBUF_DEPTH=128,
    parameter BIASBUF_DEPTH=128,

    parameter LINEBUFFER_LEN1=15,
    parameter LINEBUFFER_LEN2=13,
    parameter LINEBUFFER_LEN3=26,
    parameter LINEBUFFER_LEN4=52,
    parameter LINEBUFFER_LEN5=104,
    parameter LINEBUFFER_LEN6=208,

    parameter IFM_RAM_STYLE="block",
    parameter WEIGHT_RAM_STYLE="distributed",
    parameter BIAS_RAM_STYLE="distributed",
    parameter OFM_RAM_STYLE="block"
)
(
    input clk,
    input rst,
    output ap_done,

    // axi-lite interface
    input wire [4:0] S_AXI_LITE_CTRL_awaddr,
    input wire [2:0] S_AXI_LITE_CTRL_awprot,
    input wire  S_AXI_LITE_CTRL_awvalid,
    output wire  S_AXI_LITE_CTRL_awready,
    input wire [31:0] S_AXI_LITE_CTRL_wdata,
    input wire [3:0] S_AXI_LITE_CTRL_wstrb,
    input wire  S_AXI_LITE_CTRL_wvalid,
    output wire  S_AXI_LITE_CTRL_wready,
    output wire [1:0] S_AXI_LITE_CTRL_bresp,
    output wire  S_AXI_LITE_CTRL_bvalid,
    input wire  S_AXI_LITE_CTRL_bready,
    input wire [4:0] S_AXI_LITE_CTRL_araddr,
    input wire [2:0] S_AXI_LITE_CTRL_arprot,
    input wire  S_AXI_LITE_CTRL_arvalid,
    output wire  S_AXI_LITE_CTRL_arready,
    output wire [31:0] S_AXI_LITE_CTRL_rdata,
    output wire [1:0] S_AXI_LITE_CTRL_rresp,
    output wire  S_AXI_LITE_CTRL_rvalid,
    input wire  S_AXI_LITE_CTRL_rready,

    // axi-stream slave interface
    output wire  S_AXIS_tready,
    input wire [63:0] S_AXIS_tdata,
    input wire  S_AXIS_tlast,
    input wire  S_AXIS_tvalid,

    // axi-stream master interface
    output wire  M_AXIS_tvalid,
    output wire [63:0] M_AXIS_tdata,
    output wire  M_AXIS_tlast,
    input wire  M_AXIS_tready
);
    timeunit 1ns;
    timeprecision 1ps;
    Accel_Conv #(
        .FM_ADDR_BIT(FM_ADDR_BIT),
        .WEIGHT_AXI_ADDR_BIT(WEIGHT_AXI_ADDR_BIT),
        .WEIGHTBUF_ADDR_BIT(WEIGHTBUF_ADDR_BIT),
        .BIASBUF_ADDR_BIT(BIASBUF_ADDR_BIT),
        .FM_DEPTH(FM_DEPTH),
        .WEIGHTBUF_DEPTH(WEIGHTBUF_DEPTH),
        .BIASBUF_DEPTH(BIASBUF_DEPTH),
        .LINEBUFFER_LEN1(LINEBUFFER_LEN1),
        .LINEBUFFER_LEN2(LINEBUFFER_LEN2),
        .LINEBUFFER_LEN3(LINEBUFFER_LEN3),
        .LINEBUFFER_LEN4(LINEBUFFER_LEN4),
        .LINEBUFFER_LEN5(LINEBUFFER_LEN5),
        .LINEBUFFER_LEN6(LINEBUFFER_LEN6),
        .IFM_RAM_STYLE(IFM_RAM_STYLE),
        .WEIGHT_RAM_STYLE(WEIGHT_RAM_STYLE),
        .BIAS_RAM_STYLE(BIAS_RAM_STYLE),
        .OFM_RAM_STYLE(OFM_RAM_STYLE)
    ) u_core (.*);
endmodule
