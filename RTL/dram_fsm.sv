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
    output logic [2:0] o_dram_cmd,
    output logic [ROW_WIDTH-1:0] o_dram_addr,
    output logic [DATA_WIDTH-1:0] o_dram_wdata,
    input logic [DATA_WIDTH-1:0] i_dram_rdata,

    //AXI Interface
    output logic o_resp_valid,
    output logic [DATA_WIDTH-1:0] o_resp_data
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

    // Latched copy of the accepted request (arbiter drops it after the handshake)
    logic                  is_wr_q;
    logic [ADDR_WIDTH-1:0] addr_q;
    logic [DATA_WIDTH-1:0] data_q;
    logic [DATA_WIDTH-1:0] resp_data_q;

    // Live (incoming) request decode - used only in IDLE
    logic [ROW_WIDTH-1:0] req_row;
    assign req_row = i_req_addr[COL_WIDTH + ROW_WIDTH - 1 : COL_WIDTH];

    // Latched request decode - used in every state after IDLE
    logic [ROW_WIDTH-1:0] q_row;
    logic [COL_WIDTH-1:0] q_col;
    assign q_row = addr_q[COL_WIDTH + ROW_WIDTH - 1 : COL_WIDTH];
    assign q_col = addr_q[COL_WIDTH-1:0];

    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            current_state <= DRAM_IDLE;
            timer_curr    <= 4'd0;
            row_open_q    <= 1'b0;
            active_row_q  <= '0;
            is_wr_q       <= 1'b0;
            addr_q        <= '0;
            data_q        <= '0;
        end else begin
            current_state <= next_state;
            timer_curr    <= timer_next;
            row_open_q    <= row_open_d;
            active_row_q  <= active_row_d;

            // Capture request on the accepting (IDLE) cycle
            if (current_state == DRAM_IDLE && i_req_valid) begin
                is_wr_q <= i_req_is_write;
                addr_q  <= i_req_addr;
                data_q  <= i_req_data;
            end
        end
    end

    always_comb begin
        next_state   = current_state;
        timer_next   = timer_curr;
        row_open_d   = row_open_q;
        active_row_d = active_row_q;

        // Ready ONLY in IDLE: the only state that actually consumes a request
        o_req_ready  = (current_state == DRAM_IDLE);

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
                            // ROW HIT
                            if (i_req_is_write)
                                next_state = DRAM_WRITE;
                            else begin
                                next_state = DRAM_READ;
                                timer_next = TCAS - 1;
                            end
                        end else begin
                            // ROW MISS: precharge first
                            next_state = DRAM_PRE;
                            timer_next = TRP - 1; 
                            o_dram_cmd = CMD_PRE;
                            row_open_d = 1'b0;
                        end
                    end else begin
                        next_state   = DRAM_ACT;
                        timer_next   = TRCD - 1;
                        o_dram_cmd   = CMD_ACT;
                        o_dram_addr  = req_row;
                        row_open_d   = 1'b1;
                        active_row_d = req_row;
                    end
                end
            end

            DRAM_ACT: begin
                if (timer_curr == 0) begin
                    if (is_wr_q)
                        next_state = DRAM_WRITE;
                    else begin
                        next_state = DRAM_READ;
                        timer_next = TCAS - 1;
                    end
                end
            end

            DRAM_READ: begin
                o_dram_cmd  = CMD_RD;
                o_dram_addr = {{(ROW_WIDTH-COL_WIDTH){1'b0}}, q_col};
                if (timer_curr == 0) begin
                    next_state = DRAM_IDLE;
                end
            end

            DRAM_WRITE: begin
                o_dram_cmd   = CMD_WR;
                o_dram_addr  = {{(ROW_WIDTH-COL_WIDTH){1'b0}}, q_col};
                o_dram_wdata = data_q;
                next_state   = DRAM_IDLE;
            end

            DRAM_PRE: begin
                if (timer_curr == 0) begin
                    next_state   = DRAM_ACT;
                    timer_next   = TRCD - 1;
                    o_dram_cmd   = CMD_ACT;
                    o_dram_addr  = q_row;
                    row_open_d   = 1'b1;
                    active_row_d = q_row;
                end
            end

            default: next_state = DRAM_IDLE;
        endcase
    end

    // Response: valid and data are registered TOGETHER so they are aligned
    assign o_resp_data = resp_data_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            o_resp_valid <= 1'b0;
            resp_data_q  <= '0;
        end else begin
            o_resp_valid <= (current_state == DRAM_READ && timer_curr == 0);
            if (current_state == DRAM_READ && timer_curr == 0)
                resp_data_q <= i_dram_rdata;
        end
    end

endmodule