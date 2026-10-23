// Module: tb_npu_pin_replay
// Description: Four-state replay of Verilator-validated pins against the mapped GTP netlist.
module tb_npu_pin_replay;
    timeunit 1ns;
    timeprecision 1ps;
    logic clk = 0, rst = 1, scan_shift = 0, scan_update = 0, scan_capture = 0, scan_din = 0;
    wire scan_dout;
    string trace_path;
    int fd, rc, word_value, cycles = 0;
    npu_measure_top dut (.clk, .rst, .scan_shift, .scan_update, .scan_capture, .scan_din, .scan_dout);
    initial begin
        if (!$value$plusargs("TRACE=%s", trace_path)) $fatal(1, "missing TRACE");
        fd = $fopen(trace_path, "r");
        if (!fd) $fatal(1, "cannot open TRACE");
        while (!$feof(fd)) begin
            rc = $fscanf(fd, "%h\n", word_value);
            if (rc == 1) begin
                clk = 0;
                {rst, scan_shift, scan_update, scan_capture, scan_din} = 5'(word_value >> 1);
                #5;
                clk = 1;
                #5;
                cycles++;
                if (scan_dout !== word_value[0])
                    $fatal(1, "mapped pin mismatch at cycle %0d: got %b expected %b", cycles, scan_dout, word_value[0]);
            end else if (!$feof(fd)) $fatal(1, "malformed TRACE");
        end
        $fclose(fd);
        if (cycles == 0) $fatal(1, "empty TRACE");
        $display("PASS mapped NPU pin replay: %0d cycles, four-state GTP models", cycles);
        $finish;
    end
endmodule
