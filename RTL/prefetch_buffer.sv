import mem_ctrl_pkg::*;

module prefetch_buffer(
    input logic clk,
    input logic rst_n,
    
    //AXI4-Lite Interface
    input  logic i_lookup_valid,
    input  logic [ADDR_WIDTH-1:0] i_lookup_addr,
    
    output logic o_lookup_hit,
    output logic [DATA_WIDTH-1:0] o_lookup_data,

    //DRAM Routing (DATA FILL Interface)
    input logic i_fill_valid,
    input logic [ADDR_WIDTH-1:0] i_fill_addr,
    input logic [DATA_WIDTH-1:0] i_fill_data,

    //Write invalidate (a demand write to an address held in the PB kills the entry)
    input logic i_inval_valid,
    input logic [ADDR_WIDTH-1:0] i_inval_addr
);

    logic [ADDR_WIDTH-1:0] tag_array [PB_DEPTH-1:0];
    logic [DATA_WIDTH-1:0] data_array [PB_DEPTH-1:0];
    logic [PB_DEPTH-1:0] valid_array;

    logic [PB_INDEX_WIDTH-1:0] write_ptr;

    //CAM lookup logic
    always_comb begin
        o_lookup_hit = 1'b0;
        o_lookup_data = '0;
        if(i_lookup_valid) begin
            for(int i = 0; i < PB_DEPTH; i++) begin
                if(valid_array[i] && (tag_array[i] == i_lookup_addr)) begin
                    o_lookup_hit = 1'b1;
                    o_lookup_data = data_array[i];
                end
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            valid_array <= '0;
            write_ptr <= '0;
            for(int i = 0; i < PB_DEPTH; i++) begin
                tag_array[i] <= '0;
                data_array[i] <= '0;
            end
        end else begin
            if (o_lookup_hit) begin
                for(int i=0; i<PB_DEPTH; i++) begin
                    if(valid_array[i] && (tag_array[i] == i_lookup_addr)) begin
                        valid_array[i] <= 1'b0; // Hit-and-invalidate
                    end
                end
            end

            if (i_inval_valid) begin
                for(int i=0; i<PB_DEPTH; i++) begin
                    if(valid_array[i] && (tag_array[i] == i_inval_addr)) begin
                        valid_array[i] <= 1'b0; // Write invalidates stale prefetched data
                    end
                end
            end

            if(i_fill_valid) begin //FILLING DATA FROM DRAM (SPECULATIVE PREFETCH)
                tag_array[write_ptr] <= i_fill_addr;
                data_array[write_ptr] <= i_fill_data;
                valid_array[write_ptr] <= 1'b1;
                write_ptr <= write_ptr + 1;
            end
        end
    end

endmodule