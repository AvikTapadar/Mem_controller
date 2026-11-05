`timescale 1ns / 1ps
import mem_ctrl_pkg::*;

//MEM_CTRL_TOP_MODULE
module top #(  
    parameter ROW_WIDTH = 14,
    parameter COL_WIDTH = 8
)(
    input logic clk,
    input logic rst_n,

    // AXI4-Lite Slave Interface
    input  logic [ADDR_WIDTH-1:0] s_axi_awaddr,
    input  logic s_axi_awvalid,
    output logic s_axi_awready,
    input  logic [DATA_WIDTH-1:0] s_axi_wdata,
    input  logic [STRB_WIDTH-1:0] s_axi_wstrb,
    input  logic s_axi_wvalid,
    output logic s_axi_wready,
    output logic [1:0] s_axi_bresp,
    output logic s_axi_bvalid,
    input  logic s_axi_bready,
    input  logic [ADDR_WIDTH-1:0] s_axi_araddr,
    input  logic s_axi_arvalid,
    output logic s_axi_arready,
    output logic [DATA_WIDTH-1:0] s_axi_rdata,
    output logic [1:0] s_axi_rresp,
    output logic s_axi_rvalid,
    input  logic s_axi_rready,

    //DRAM interface
    output logic [2:0] o_dram_cmd,
    output logic [ROW_WIDTH-1:0] o_dram_addr,
    output logic [DATA_WIDTH-1:0] o_dram_wdata,
    input  logic [DATA_WIDTH-1:0] i_dram_rdata
);

    // AXI to Internal
    logic axi_rd_valid, axi_rd_ready;
    logic [ADDR_WIDTH-1:0] axi_rd_addr;
    logic axi_wr_valid, axi_wr_ready;
    logic [ADDR_WIDTH-1:0] axi_wr_addr;
    logic [DATA_WIDTH-1:0] axi_wr_data;

    // PB to Internal
    logic pb_hit;
    logic [DATA_WIDTH-1:0] pb_data;

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

    //Module Instantiations
    AXI_lite_slave u_axi_slave (
        .aclk               (aclk),
        .aresetn            (aresetn),
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
        
        // Internal Demand Interfaces mapped to wires
        .o_read_req_valid   (axi_rd_valid),
        .o_read_req_addr    (axi_rd_addr),
        .i_read_req_ready   (axi_rd_ready),
        .i_read_resp_valid  (axi_read_resp_valid),
        .i_read_resp_data   (axi_read_resp_data),
        .o_read_resp_ready  (), // Unused, we don't backpressure FSM reads
        
        .o_write_req_valid  (axi_wr_valid),
        .o_write_req_addr   (axi_wr_addr),
        .o_write_req_data   (axi_wr_data),
        .o_write_req_strb   (), 
        .i_write_req_ready  (arb_wr_ready),
        .i_write_resp_valid (axi_write_resp_valid),
        .o_write_resp_ready ()
    );

    stride_prefetcher #(
        .TABLE_INDEX_BITS(4)
    ) u_stride_engine (
        .clk                (aclk),
        .rst_n              (aresetn),
        .addr_in            (axi_rd_addr),
        // Only snoop if the read was successfully accepted by PB or Arbiter
        .valid_in           (axi_rd_valid && axi_rd_ready), 
        .prefetch_addr_out  (pref_req_addr),
        .valid_out          (pref_req_valid),
        .prefetch_ready     (pref_req_ready)
    );

    prefetch_buffer u_pb (
        .clk                (aclk),
        .rst_n              (aresetn),
        .i_lookup_valid     (axi_rd_valid),
        .i_lookup_addr      (axi_rd_addr),
        .o_lookup_hit       (pb_hit),
        .o_lookup_data      (pb_data),
        .i_fill_valid       (pb_fill_valid),
        .i_fill_addr        (pb_fill_addr),
        .i_fill_data        (fsm_resp_data)
    );

    fr_fcfs_arbiter #(
        .ROW_WIDTH(ROW_WIDTH), .COL_WIDTH(COL_WIDTH)
    ) u_arbiter (
        .clk                (aclk),
        .rst_n              (aresetn),
        // Only send demand read to Arbiter if it MISSED the Prefetch Buffer
        .i_read_valid       (axi_rd_valid && !pb_hit), 
        .i_read_addr        (axi_rd_addr),
        .o_read_ready       (arb_rd_ready),
        
        .i_write_valid      (axi_wr_valid),
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

    dram_fsm #(
        .TRCD(4), .TCAS(4), .TRP(4),
        .ROW_WIDTH(ROW_WIDTH), .COL_WIDTH(COL_WIDTH)
    ) u_dram_fsm (
        .clk                (aclk),
        .rst_n              (aresetn),
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

    // Custom Routing & Data Interception Logic

    // Track if the outstanding DRAM read is a speculative prefetch
    logic in_flight_is_pref;
    logic [ADDR_WIDTH-1:0] in_flight_addr;

    always_ff @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            in_flight_is_pref <= 1'b0;
            in_flight_addr    <= '0;
        end else if (fsm_req_valid && fsm_req_ready && !fsm_req_is_write) begin
            // It is a prefetch if the arbiter accepted a prefetch req but NOT a demand read req
            in_flight_is_pref <= pref_req_ready && !arb_rd_ready;
            in_flight_addr    <= fsm_req_addr;
        end
    end

    // 1. Read Request Routing
    // AXI Read is "ready/accepted" immediately if PB hits. Otherwise, wait for Arbiter to accept.
    assign axi_rd_ready = pb_hit ? 1'b1 : arb_rd_ready;

    // 2. Read Response Routing back to AXI
    logic axi_read_resp_valid;
    logic [DATA_WIDTH-1:0] axi_read_resp_data;
    
    // AXI returns data instantly from PB (Hit), or later from FSM (Miss)
    assign axi_read_resp_valid = pb_hit || (fsm_resp_valid && !in_flight_is_pref);
    assign axi_read_resp_data  = pb_hit ? pb_data : fsm_resp_data;

    // 3. Prefetch Buffer Data Fill Routing
    // Fill PB only if the returning FSM data belongs to an in-flight speculative prefetch
    assign pb_fill_valid = fsm_resp_valid && in_flight_is_pref;
    assign pb_fill_addr  = in_flight_addr;

    // 4. Write Response Routing
    logic axi_write_resp_valid;
    // Writes complete in FSM instantly once accepted, trigger BVALID response back to host
    assign axi_write_resp_valid = fsm_req_valid && fsm_req_ready && fsm_req_is_write;
endmodule