import mem_ctrl_pkg::*;
module dram_fsm #( 
    // JEDEC Timing Constraints (in clock cycles)
    parameter TRCD = 4, // RAS-to-CAS Delay (Activate to Read/Write)
    parameter TCAS = 4, // CAS Latency (Read command to Data Valid)
    parameter TRP  = 4, // Row Precharge Time (Precharge to next Activate)
    
    // Address Decoding (assuming 32-bit addr, 8-bit col, 14-bit row for simulation)
    parameter ROW_WIDTH = 14,
    parameter COL_WIDTH = 8
)(
    input logic clk,
    input logic rst_n,

    //Arbiter Interface
    input logic i_req_valid,
    input logic i_req_is_write,
    input logic [ADDR_WIDTH-1:0] i_req_addr,
    input logic [DATA_WIDTH-1:0] i_req_data,
    output logic o_req_ready,

    //DRAM Interface
    output logic o_dram_cmd,
    output logic [ADDR_WIDTH-1:0] o_dram_addr,
    output logic [DATA_WIDTH-1:0] o_dram_wdata,
    input logic [DATA_WIDTH-1:0] i_dram_rdata,

    //AXI Interface
    output logic o_resp_valid,
    output logic [DATA_WIDTH-1:0] o_resp_data,
);

    //Command Encoding for DRAM
    localparam CMD_NOP = 3'b000;
    localparam CMD_ACT = 3'b001;
    localparam CMD_RD  = 3'b010;
    localparam CMD_WR  = 3'b011;
    localparam CMD_PRE = 3'b100;

    dram_state_t current_state, next_state;
    logic [3:0] timer_curr, timer_next; //JEDEC Timing Timer to cover delays

    // Open Row Tracking
    logic row_open_q, row_open_d;
    logic [ROW_WIDTH-1:0] active_row_q, active_row_d;

    // Address Decoding Helper
    logic [ROW_WIDTH-1:0] req_row;
    assign req_row = i_req_addr[COL_WIDTH + ROW_WIDTH - 1 : COL_WIDTH];

    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            current_state <= DRAM_IDLE;
            timer_curr <= 4'd0;
            row_open_q <= 1'b0;
            active_row_q <= '0;
        end else begin
            current_state <= next_state;
            timer_curr <= timer_next;
            row_open_q <= row_open_d;
            active_row_q <= active_row_d;
        end
    end

    always_comb begin
        next_state = current_state;
        timer_next = timer_curr;
        row_open_d = row_open_q;
        active_row_d = active_row_q;

        o_req_ready  = 1'b0;
        o_resp_valid = 1'b0;
        o_resp_data  = '0;
        
        o_dram_cmd   = CMD_NOP;
        o_dram_addr  = '0;
        o_dram_wdata = '0;

        if (timer_curr > 0) begin
            timer_next = timer_curr - 1'b1;
        end

        case(current_state)
            DRAM_IDLE: begin
                if(i_req_valid) begin
                    if (row_open_q) begin
                        if (active_row_q == req_row) begin
                            // ROW HIT: Row is already open, skip straight to Read/Write
                            next_state = i_req_is_write ? DRAM_WRITE : DRAM_READ;
                        end else begin
                            // ROW MISS: A different row is open, must precharge first
                            next_state = DRAM_PRE;
                            timer_next = TRP - 1; 
                            o_dram_cmd = CMD_PRE;
                            row_open_d = 1'b0;
                        end
                    end else begin
                       next_state = DRAM_ACT;
                        timer_next = TRCD - 1;
                        o_dram_cmd = CMD_ACT;
                        o_dram_addr = req_row;
                        row_open_d = 1'b1;
                        active_row_d = req_row;
                    end
                end
            end

            DRAM_ACT: begin
                if (timer_curr == 0) begin
                    next_state = i_req_is_write ? DRAM_WRITE : DRAM_READ;
                end
            end

            DRAM_READ: begin
                o_dram_cmd  = CMD_RD;
                o_dram_addr = i_req_addr[COL_WIDTH-1:0]; // Send column address
                timer_next = TCAS - 1;
                
                // When Column delay finishes, data is valid
                if (timer_curr == 0) begin
                    o_resp_valid = 1'b1;
                    o_resp_data = i_dram_rdata;
                    o_req_ready = 1'b1; // Tell arbiter we are done, accept next
                    next_state = DRAM_IDLE;
                end
            end

            DRAM_WRITE: begin
                o_dram_cmd = CMD_WR;
                o_dram_addr = i_req_addr[COL_WIDTH-1:0];
                o_dram_wdata = i_req_data;
                
                // Writes complete essentially immediately on the bus
                o_req_ready = 1'b1;
                next_state = DRAM_IDLE;
            end

            DRAM_PRE: begin
                if (timer_curr == 0) begin
                    next_state = DRAM_ACT;
                    timer_next = TRCD - 1;
                    o_dram_cmd = CMD_ACT;
                    o_dram_addr = req_row;
                    row_open_d = 1'b1;
                    active_row_d = req_row;
                end
            end

            default: next_state = DRAM_IDLE;
        endcase
    end


endmodule 