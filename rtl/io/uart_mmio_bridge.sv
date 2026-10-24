// SPDX-License-Identifier: Apache-2.0
// Stop-and-wait framed UART bytes -> exactly one local MMIO transaction.
// CRC16/CCITT-FALSE; cache the last completed transaction to make retries safe.
module uart_mmio_bridge #(
    parameter int INTERBYTE_TIMEOUT = 2700000,
    parameter int TW = $clog2(INTERBYTE_TIMEOUT) < 1 ? 1 : $clog2(INTERBYTE_TIMEOUT)
) (
    input logic clk, rst,
    input logic rx_valid, rx_error,
    input logic [7:0] rx_data,
    output logic tx_valid,
    input logic tx_ready,
    output logic [7:0] tx_data,
    output logic req_valid,
    input logic req_ready,
    output logic req_write,
    output logic [15:0] req_addr,
    output logic [31:0] req_wdata,
    output logic [3:0] req_wstrb,
    input logic rsp_valid,
    output logic rsp_ready,
    input logic [31:0] rsp_rdata,
    input logic rsp_error
);
    timeunit 1ns;
    timeprecision 1ps;
    typedef enum logic [2:0] {RECEIVE, BUS_REQUEST, BUS_RESPONSE, REPLY_CRC, SEND} state_t;
    state_t state_q;
    logic [3:0] rx_index_q, tx_index_q, crc_index_q;
    logic [TW-1:0] timeout_q;
    logic [79:0] request_q, cached_request_q, reply_prefix_q;
    logic [15:0] rx_crc_q, reply_crc_q, next_reply_crc;
    logic [7:0] received_crc_lo_q;
    logic [95:0] reply_q, cached_reply_q;
    logic cache_valid_q, cache_pending_q, format_ok;
    function automatic logic [15:0] crc_byte(input logic [15:0] crc, input logic [7:0] data);
        logic [15:0] value;
        begin
            value = crc ^ {data, 8'd0};
            for (int bit_index = 0; bit_index < 8; bit_index++)
                value = value[15] ? (value << 1) ^ 16'h1021 : value << 1;
            return value;
        end
    endfunction
    function automatic logic [79:0] prefix(
        input logic [7:0] sequence_number, status, input logic [31:0] data
    );
        return {data, 8'd0, status, sequence_number, 8'd1, 8'ha5, 8'h5a};
    endfunction
    assign format_ok = request_q[7:0] == 1 && request_q[31:28] == 0 &&
        ((request_q[23:16] == 0 && request_q[31:24] == 0 && request_q[79:48] == 0) ||
          request_q[23:16] == 1 ||
         (request_q[23:16] == 2 && request_q[47:24] == 0));
    assign req_valid = !rst && state_q == BUS_REQUEST;
    assign req_write = request_q[23:16] == 1;
    assign req_addr = request_q[47:32];
    assign req_wdata = request_q[79:48];
    assign req_wstrb = request_q[27:24];
    assign rsp_ready = !rst && state_q == BUS_RESPONSE;
    assign tx_valid = !rst && state_q == SEND;
    assign tx_data = reply_q[7:0];
    assign next_reply_crc = crc_byte(reply_crc_q, reply_prefix_q[crc_index_q*8 +: 8]);
    always_ff @(posedge clk) begin
        if (rst) begin
            state_q <= RECEIVE;
            rx_index_q <= '0;
            tx_index_q <= '0;
            crc_index_q <= 4'd2;
            timeout_q <= '0;
            request_q <= '0;
            cached_request_q <= '0;
            reply_prefix_q <= '0;
            reply_q <= '0;
            cached_reply_q <= '0;
            rx_crc_q <= 16'hffff;
            reply_crc_q <= 16'hffff;
            received_crc_lo_q <= '0;
            cache_valid_q <= 1'b0;
            cache_pending_q <= 1'b0;
        end else begin
            if (state_q != REPLY_CRC) begin reply_crc_q <= 16'hffff; crc_index_q <= 4'd2; end
            unique case (state_q)
                RECEIVE: begin
                    if (rx_error) begin rx_index_q <= '0; timeout_q <= '0; rx_crc_q <= 16'hffff; end
                    else if (rx_valid) begin
                        timeout_q <= '0;
                        unique case (rx_index_q)
                            0: if (rx_data == 8'ha5) rx_index_q <= 1;
                            1: if (rx_data == 8'h5a) begin rx_index_q <= 2; rx_crc_q <= 16'hffff; end
                               else if (rx_data != 8'ha5) rx_index_q <= 0;
                            12: begin received_crc_lo_q <= rx_data; rx_index_q <= 13; end
                            13: begin
                                rx_index_q <= 0;
                                cache_pending_q <= 1'b0;
                                state_q <= REPLY_CRC;
                                if ({rx_data, received_crc_lo_q} != rx_crc_q)
                                    reply_prefix_q <= prefix(request_q[15:8], 3, 0);
                                else if (!format_ok) reply_prefix_q <= prefix(request_q[15:8], 2, 0);
                                else if (request_q[23:16] == 2) begin
                                    cache_valid_q <= 1'b0;
                                    reply_prefix_q <= prefix(request_q[15:8], 0, request_q[79:48]);
                                end else if (cache_valid_q && request_q[15:8] == cached_request_q[15:8]) begin
                                    if (request_q == cached_request_q) begin
                                        reply_q <= cached_reply_q;
                                        tx_index_q <= 0;
                                        state_q <= SEND;
                                    end else reply_prefix_q <= prefix(request_q[15:8], 4, 0);
                                end else state_q <= BUS_REQUEST;
                            end
                            default: begin
                                request_q[(rx_index_q-4'd2)*8 +: 8] <= rx_data;
                                rx_crc_q <= crc_byte(rx_crc_q, rx_data);
                                rx_index_q <= rx_index_q + 1'b1;
                            end
                        endcase
                    end else if (rx_index_q != 0) begin
                        if (timeout_q == TW'(INTERBYTE_TIMEOUT-1)) begin
                            rx_index_q <= '0; timeout_q <= '0; rx_crc_q <= 16'hffff;
                        end else timeout_q <= timeout_q + 1'b1;
                    end
                end
                BUS_REQUEST: if (req_ready) state_q <= BUS_RESPONSE;
                BUS_RESPONSE: if (rsp_valid) begin
                    reply_prefix_q <= prefix(request_q[15:8], rsp_error ? 8'd1 : 8'd0, rsp_rdata);
                    cached_request_q <= request_q;
                    cache_pending_q <= 1'b1;
                    state_q <= REPLY_CRC;
                end
                REPLY_CRC: begin
                    reply_crc_q <= next_reply_crc;
                    if (crc_index_q == 9) begin
                        reply_q <= {next_reply_crc, reply_prefix_q};
                        tx_index_q <= 0;
                        if (cache_pending_q) begin
                            cached_reply_q <= {next_reply_crc, reply_prefix_q};
                            cache_valid_q <= 1'b1;
                            cache_pending_q <= 1'b0;
                        end
                        state_q <= SEND;
                    end else crc_index_q <= crc_index_q + 1'b1;
                end
                SEND: if (tx_ready) begin
                    reply_q <= {8'd0, reply_q[95:8]};
                    if (tx_index_q == 11) state_q <= RECEIVE;
                    else tx_index_q <= tx_index_q + 1'b1;
                end
                default: state_q <= RECEIVE;
            endcase
        end
    end
endmodule
