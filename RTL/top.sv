`timescale 1ns / 1ps
import mem_ctrl_pkg::*;

//MEM_CTRL_TOP_MODULE
module top #(  
    parameter ROW_WIDTH = 14,
    parameter COL_WIDTH = 8
)(
    input logic clk,
    input logic rst_n,

    //AXI Interface
    input logic [ADDR_WIDTH-1:0] awaddr,
    input logic awvalid,
    output logic awready,
    input logic [DATA_WIDTH-1:0] wdata,
    input logic [STRB_WIDTH-1:0] wstrb,
    input logic wvalid,
    output logic wready,
    output logic [1:0] bresp,
    output logic bvalid,
    input logic bready,
    input logic [ADDR_WIDTH-1:0] araddr,
    input logic arvalid,
    output logic arready,
    output logic [DATA_WIDTH-1:0] rdata,
    output logic [1:0] rresp,
    output logic rvalid,
    input logic rready,

    //DRAM interface
    output logic [2:0] o_dram_cmd,
    output logic [ROW_WIDTH-1:0] o_dram_addr,
    output logic [DATA_WIDTH-1:0] o_dram_wdata,
    input  logic [DATA_WIDTH-1:0] i_dram_rdata
);

    // AXI to Internal
    logic axi_rd_valid, axi_rd_ready;
    logic [ADDR_WIDTH-1:0] axi_rd_addr;
    logic axi_wr_valid;
    logic [ADDR_WIDTH-1:0] axi_wr_addr;
    logic [DATA_WIDTH-1:0] axi_wr_data;

    // PB to Internal
    logic pb_hit;
    logic [DATA_WIDTH-1:0] pb_data;
    logic pb_fill_valid;
    logic [ADDR_WIDTH-1:0] pb_fill_addr;

    //Stride to Arbiter 
    logic pref_req_valid, pref_req_ready;
    logic [ADDR_WIDTH-1:0] pref_req_addr;

    // Arbiter to FSM
    logic fsm_req_valid, fsm_req_ready, fsm_req_is_write;
    logic [ADDR_WIDTH-1:0] fsm_req_addr;
    logic [DATA_WIDTH-1:0] fsm_req_data;

    //FSM to internal 
    logic fsm_resp_valid;
    logic [DATA_WIDTH-1:0] fsm_resp_data;

    // Arbiter Handshakes
    logic arb_rd_ready, arb_wr_ready;

    // In-flight requests
    logic in_flight_is_pref;
    logic [ADDR_WIDTH-1:0] in_flight_addr;

    // AXI response holding registers (valid stays high until ready)
    logic rd_busy, r_vld;
    logic [DATA_WIDTH-1:0] r_data;
    logic wr_busy, b_vld;

    wire ar_fire = axi_rd_valid && axi_rd_ready;   // read accepted
    wire wr_fire = axi_wr_valid && arb_wr_ready;   // write accepted

    //Module Instantiations
    AXI_lite_slave u_axi_slave (
        .aclk               (clk),
        .aresetn            (rst_n),
        .awaddr             (awaddr),
        .awvalid            (awvalid),
        .awready            (awready),
        .wdata              (wdata),
        .wstrb              (wstrb),
        .wvalid             (wvalid),
        .wready             (wready),
        .bresp              (bresp),
        .bvalid             (bvalid),
        .bready             (bready),
        .araddr             (araddr),
        .arvalid            (arvalid),
        .arready            (arready),
        .rdata              (rdata),
        .rresp              (rresp),
        .rvalid             (rvalid),
        .rready             (rready),
        
        .o_read_req_valid   (axi_rd_valid),
        .o_read_req_addr    (axi_rd_addr),
        .i_read_req_ready   (axi_rd_ready),
        .i_read_resp_valid  (r_vld),
        .i_read_resp_data   (r_data),
        .o_read_resp_ready  (),
        
        .o_write_req_valid  (axi_wr_valid),
        .o_write_req_addr   (axi_wr_addr),
        .o_write_req_data   (axi_wr_data),
        .o_write_req_strb   (), 
        .i_write_req_ready  (arb_wr_ready),
        .i_write_resp_valid (b_vld),
        .o_write_resp_ready ()
    );

    stride_prefetcher u_stride_engine (
        .clk                (clk),
        .rst_n              (rst_n),
        .addr_in            (axi_rd_addr),
        .valid_in           (ar_fire), 
        .prefetch_addr_out  (pref_req_addr),
        .valid_out          (pref_req_valid),
        .prefetch_ready     (pref_req_ready)
    );

    prefetch_buffer u_pb (
        .clk                (clk),
        .rst_n              (rst_n),
        .i_lookup_valid     (axi_rd_valid && !rd_busy),
        .i_lookup_addr      (axi_rd_addr),
        .o_lookup_hit       (pb_hit),
        .o_lookup_data      (pb_data),
        .i_fill_valid       (pb_fill_valid),
        .i_fill_addr        (pb_fill_addr),
        .i_fill_data        (fsm_resp_data),
        .i_inval_valid      (wr_fire),
        .i_inval_addr       (axi_wr_addr)
    );

    dram_fsm #(
        .TRCD(4), .TCAS(4), .TRP(4),
        .ROW_WIDTH(ROW_WIDTH), .COL_WIDTH(COL_WIDTH)
    ) u_dram_fsm (
        .clk                (clk),
        .rst_n              (rst_n),
        .i_req_valid        (fsm_req_valid),
        .i_req_is_write     (fsm_req_is_write),
        .i_req_addr         (fsm_req_addr),
        .i_req_data         (fsm_req_data),
        .o_req_ready        (fsm_req_ready),
        
        .o_dram_cmd         (o_dram_cmd),
        .o_dram_addr        (o_dram_addr),
        .o_dram_wdata       (o_dram_wdata),
        .i_dram_rdata       (i_dram_rdata),
        
        .o_resp_valid       (fsm_resp_valid),
        .o_resp_data        (fsm_resp_data)
    );

    fr_fcfs_arbiter #(
        .ROW_WIDTH(ROW_WIDTH), .COL_WIDTH(COL_WIDTH)
    ) u_arbiter (
        .clk                (clk),
        .rst_n              (rst_n),
        // Only forward a demand read that missed the PB and has no read outstanding
        .i_read_valid       (axi_rd_valid && !rd_busy && !pb_hit), 
        .i_read_addr        (axi_rd_addr),
        .o_read_ready       (arb_rd_ready),
        
        // Only forward a write if no write response is still outstanding
        .i_write_valid      (axi_wr_valid && !wr_busy),
        .i_write_addr       (axi_wr_addr),
        .i_write_data       (axi_wr_data),
        .o_write_ready      (arb_wr_ready),
        
        .i_prefetch_valid   (pref_req_valid),
        .i_prefetch_addr    (pref_req_addr),
        .o_prefetch_ready   (pref_req_ready),
        
        .o_fsm_valid        (fsm_req_valid),
        .o_fsm_addr         (fsm_req_addr),
        .i_fsm_ready        (fsm_req_ready),
        .o_fsm_is_write     (fsm_req_is_write),
        .o_fsm_data         (fsm_req_data)
    );

    // Track if the outstanding DRAM read is a speculative prefetch
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            in_flight_is_pref <= 1'b0;
            in_flight_addr <= '0;
        end else if (fsm_req_valid && fsm_req_ready && !fsm_req_is_write) begin
            in_flight_is_pref <= pref_req_ready;   // only high when the prefetch branch was granted
            in_flight_addr <= fsm_req_addr;
        end
    end

    // Read request routing: one outstanding read at a time
    assign axi_rd_ready = !rd_busy && (pb_hit ? 1'b1 : arb_rd_ready);

    // Prefetch Buffer fill routing
    wire pref_addr_written = wr_fire && (axi_wr_addr == in_flight_addr);
    assign pb_fill_valid = fsm_resp_valid && in_flight_is_pref && !pref_addr_written;
    assign pb_fill_addr  = in_flight_addr;

    // AXI R / B holding registers
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd_busy <= 1'b0;
            r_vld   <= 1'b0;
            r_data  <= '0;
            wr_busy <= 1'b0;
            b_vld   <= 1'b0;
        end else begin
            // Read
            if (ar_fire) rd_busy <= 1'b1;

            if (ar_fire && pb_hit) begin
                r_vld  <= 1'b1;
                r_data <= pb_data;
            end else if (fsm_resp_valid && !in_flight_is_pref) begin
                r_vld  <= 1'b1;
                r_data <= fsm_resp_data;
            end

            if (r_vld && rready) begin
                r_vld   <= 1'b0;
                rd_busy <= 1'b0;
            end

            // Write (posted: B returned once the write is accepted)
            if (wr_fire) begin
                wr_busy <= 1'b1;
                b_vld   <= 1'b1;
            end

            if (b_vld && bready) begin
                b_vld   <= 1'b0;
                wr_busy <= 1'b0;
            end
        end
    end
endmodule