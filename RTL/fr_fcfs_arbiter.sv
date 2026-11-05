import mem_ctrl_pkg::*;

module fr_fcfs_arbiter #(
    parameter ROW_WIDTH = 14,
    parameter COL_WIDTH = 8
)(
    input logic clk,
    input logic rst_n,

    //demand read interface 
    input  logic i_read_valid,
    input  logic [ADDR_WIDTH-1:0] i_read_addr,
    output logic o_read_ready,

    //demand write interface
    input  logic i_write_valid,
    input  logic [ADDR_WIDTH-1:0] i_write_addr,
    input logic [DATA_WIDTH-1:0] i_write_data,
    output logic o_write_ready,

    //prefetch interface 
    input logic i_prefetch_valid,
    input logic [ADDR_WIDTH-1:0] i_prefetch_addr,
    output logic o_prefetch_ready,

    //command interface from dram fsm 
    output logic o_fsm_valid,
    output logic [ADDR_WIDTH-1:0] o_fsm_addr,
    input logic i_fsm_ready,
    output logic o_fsm_is_write,
    output logic [DATA_WIDTH-1:0] o_fsm_data
);

    //internal signals to track dram rows
    logic row_is_open;
    logic [ROW_WIDTH-1:0] active_row;

    //Row address of the current read, write, and prefetch requests
    logic [ROW_WIDTH-1:0] read_row;
    logic [ROW_WIDTH-1:0] write_row;
    logic [ROW_WIDTH-1:0] pref_row;

    assign read_row  = i_read_addr[COL_WIDTH + ROW_WIDTH -1 : COL_WIDTH];
    assign write_row = i_write_addr[COL_WIDTH + ROW_WIDTH -1 : COL_WIDTH];
    assign pref_row  = i_prefetch_addr[COL_WIDTH + ROW_WIDTH -1 : COL_WIDTH];

    //Hit detection of row 
    logic read_is_hit;
    logic write_is_hit;

    assign read_is_hit  = i_read_valid && row_is_open && (read_row  == active_row);
    assign write_is_hit = i_write_valid && row_is_open && (write_row == active_row);

    //FR_FCFS arbitration logic (priority encoder logic: read > write > prefetch)
    always_comb begin
        o_read_ready   = 1'b0;
        o_write_ready  = 1'b0;
        o_prefetch_ready   = 1'b0;
        
        o_fsm_valid    = 1'b0;
        o_fsm_is_write = 1'b0;
        o_fsm_addr     = '0;
        o_fsm_data     = '0;

        if(read_is_hit) begin //Demand read has the highest priority (row open)
            o_read_ready = i_fsm_ready;
            o_fsm_valid    = 1'b1;
            o_fsm_addr     = i_read_addr;
            o_fsm_is_write = 1'b0;
        end 
        else if(write_is_hit) begin //Demand Write (row open)
            o_write_ready = i_fsm_ready;
            o_fsm_valid    = 1'b1;
            o_fsm_addr     = i_write_addr;
            o_fsm_is_write = 1'b1;
            o_fsm_data     = i_write_data;
        end 
        else if(i_read_valid) begin //Demand Read but row is not open
            o_fsm_valid = 1'b1;
            o_fsm_is_write = 1'b0;
            o_fsm_addr = i_read_addr;
            o_read_ready = i_fsm_ready;
        end
        else if(i_write_valid) begin //Demand Write but row is not open
            o_fsm_valid = 1'b1;
            o_fsm_is_write = 1'b1;
            o_fsm_addr = i_write_addr;
            o_fsm_data = i_write_data;
            o_write_ready = i_fsm_ready;
        end
        else if(i_prefetch_valid) begin //Prefetch request (lowest priority)
            o_fsm_valid = 1'b1;
            o_fsm_is_write = 1'b0; //Prefetch is always a read
            o_fsm_addr = i_prefetch_addr;
            o_prefetch_ready = i_fsm_ready;
        end
    end

    //Open Row Tracking Logic
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            row_is_open <= 1'b0;
            active_row <= '0;
        end
        else begin
            if(o_fsm_valid && i_fsm_ready) begin
                row_is_open <= 1'b1;
                active_row <=  o_fsm_addr[COL_WIDTH + ROW_WIDTH -1 : COL_WIDTH];
            end
        end
    end
endmodule