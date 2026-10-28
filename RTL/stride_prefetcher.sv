import mem_ctrl_pkg::*;

module stride_prefetcher #(
    parameter TABLE_INDEX_BITS = 4 // 16-entry direct-mapped table
)(
    input  logic clk,
    input  logic rst_n,
    
    input  logic [ADDR_WIDTH-1:0] addr_in,
    input  logic valid_in,
    
    output logic [ADDR_WIDTH-1:0] prefetch_addr_out,
    output logic valid_out,
    input  logic prefetch_ready // Arbiter accepted it
);

    localparam TABLE_SIZE = 2**TABLE_INDEX_BITS;

    typedef struct packed {
        logic [ADDR_WIDTH-1:0] last_addr;
        logic [ADDR_WIDTH-1:0] stride;
        logic [1:0] confidence; // 2-bit saturating counter
        logic valid;
    } stride_entry_t;

    // Direct-mapped BRAM/LUTRAM table
    stride_entry_t stride_table [TABLE_SIZE-1:0];

    // Use bits [TABLE_INDEX_BITS+1 : 2] as index (assuming 32-bit word-aligned addresses)
    logic [TABLE_INDEX_BITS-1:0] index;
    assign index = addr_in[TABLE_INDEX_BITS+1 : 2];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_out         <= 1'b0;
            prefetch_addr_out <= '0;
            for (int i = 0; i < TABLE_SIZE; i++) begin
                stride_table[i] <= '0;
            end
        end else begin
            // Clearing valid flag once the arbiter accepts the prefetch
            if (valid_out && prefetch_ready) begin
                valid_out <= 1'b0;
            end

            if (valid_in) begin
                logic [ADDR_WIDTH-1:0] current_stride;
                
                // Calculate the difference between current address and the stored address at this index
                current_stride = addr_in - stride_table[index].last_addr;

                if (stride_table[index].valid) begin
                    // If the calculated stride matches the stored stride, increase confidence
                    if (current_stride == stride_table[index].stride && current_stride != 0) begin
                        if (stride_table[index].confidence < 2'b11) begin
                            stride_table[index].confidence <= stride_table[index].confidence + 1'b1;
                        end
                        
                        // Trigger prefetch if confidence is high enough
                        if (stride_table[index].confidence >= 2'b01 && !valid_out) begin
                            valid_out <= 1'b1;
                            prefetch_addr_out <= addr_in + current_stride;
                        end
                    end else begin
                        // Stride broken: update to new stride and drop confidence
                        stride_table[index].stride <= current_stride;
                        stride_table[index].confidence <= 2'b00;
                    end
                end else begin
                    // First time allocating this index
                    stride_table[index].valid <= 1'b1;
                    stride_table[index].stride <= '0;
                    stride_table[index].confidence <= 2'b00;
                end

                // updated the last seen address for this index
                stride_table[index].last_addr <= addr_in;
            end
        end
    end

endmodule