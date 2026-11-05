`timescale 1ns / 1ps
import mem_ctrl_pkg::*;

module stride_prefetcher (
    input  logic clk,
    input  logic rst_n,
    
    input  logic [ADDR_WIDTH-1:0] addr_in,
    input  logic valid_in,
    
    output logic [ADDR_WIDTH-1:0] prefetch_addr_out,
    output logic valid_out,
    input  logic prefetch_ready // Arbiter accepted it
);

    logic [ADDR_WIDTH-1:0] last_addr;
    logic [ADDR_WIDTH-1:0] last_stride;
    logic [1:0]            confidence;
    logic                  entry_valid;

    logic [ADDR_WIDTH-1:0] current_stride;
    assign current_stride = addr_in - last_addr;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_out         <= 1'b0;
            prefetch_addr_out <= '0;
            last_addr         <= '0;
            last_stride       <= '0;
            confidence        <= 2'b00;
            entry_valid       <= 1'b0;
        end else begin
            // Clear valid flag once the arbiter accepts the prefetch
            if (valid_out && prefetch_ready) begin
                valid_out <= 1'b0;
            end

            if (valid_in) begin
                last_addr <= addr_in;

                if (entry_valid) begin
                    if (current_stride == last_stride && current_stride != 0) begin
                        if (confidence < 2'b11)
                            confidence <= confidence + 1'b1;

                        // Same trigger point as the golden model (confidence reaches 2)
                        if (confidence >= 2'b01 && !valid_out) begin
                            valid_out         <= 1'b1;
                            prefetch_addr_out <= addr_in + current_stride;
                        end
                    end else begin
                        last_stride <= current_stride;
                        confidence  <= 2'b00;
                    end
                end else begin
                    entry_valid <= 1'b1;
                    last_stride <= '0;
                    confidence  <= 2'b00;
                end
            end
        end
    end
endmodule