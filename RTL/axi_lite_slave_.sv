import mem_ctrl_pkg::*;

module AXI_lite_slave(
    input logic aclk,
    input logic aresetn,

    // AXI Write Address Channel
    input logic [ADDR_WIDTH-1:0] awaddr,
    input logic awvalid,
    output logic awready,

    // AXI Write Data Channel
    input logic [DATA_WIDTH-1:0] wdata,
    input logic [STRB_WIDTH-1:0] wstrb,
    input logic wvalid,
    output logic wready,

    // AXI Write Response Channel
    output logic [1:0] bresp,
    output logic bvalid,
    input logic bready,

    // AXI Read Address Channel
    input logic [ADDR_WIDTH-1:0] araddr,
    input logic arvalid,
    output logic arready,

    // AXI Read Data Channel
    output logic [DATA_WIDTH-1:0] rdata,
    output logic [1:0] rresp,
    output logic rvalid,
    input logic rready,

    //FR-FCFS interface and prefetch buffer interface added
    // Demand Read Interface
    output logic o_read_req_valid,
    output logic [ADDR_WIDTH-1:0] o_read_req_addr,
    input  logic i_read_req_ready,   // Arbiter accepts read
    
    input  logic i_read_resp_valid,  // PB or DRAM returns data
    input  logic [DATA_WIDTH-1:0] i_read_resp_data,
    output logic o_read_resp_ready,  // AXI passes data to Host

    // Demand Write Interface
    output logic o_write_req_valid,
    output logic [ADDR_WIDTH-1:0] o_write_req_addr,
    output logic [DATA_WIDTH-1:0] o_write_req_data,
    output logic [STRB_WIDTH-1:0] o_write_req_strb,
    input  logic i_write_req_ready,  // Arbiter accepts write
    
    input  logic i_write_resp_valid, // DRAM confirms write
    output logic o_write_resp_ready  // AXI finishes write response
);
    //i signifies input to the AXI slave, o signifies output from the AXI slave
    //s signifies AXI slave interface signals
    
    // Read Channel Logic 
    assign arready = (aresetn == 1'b1) ? i_read_req_ready : 1'b0; // Ready when not already sending a request and arbiter is ready
    assign o_read_req_valid = (aresetn == 1'b1) ? arvalid : 1'b0;
    assign o_read_req_addr  = araddr;

    // Return data to host
    assign rvalid = (aresetn == 1'b1) ? i_read_resp_valid : 1'b0;
    assign rdata  = (aresetn == 1'b1) ? i_read_resp_data : '0;
    assign rresp  = 2'b00; // OKAY response
    assign o_read_resp_ready = (aresetn == 1'b1) ? rready : 1'b0;

    // Write Channel Logic 
    logic write_handshake_ready;
    assign write_handshake_ready = awvalid && wvalid && i_write_req_ready;

    assign awready = (aresetn == 1'b1) ? write_handshake_ready : 1'b0;
    assign wready  = (aresetn == 1'b1) ? write_handshake_ready : 1'b0;

    assign o_write_req_valid = (aresetn == 1'b1) ? (awvalid && wvalid) : 1'b0;
    assign o_write_req_addr  = awaddr;
    assign o_write_req_data  = wdata;
    assign o_write_req_strb  = wstrb;

    // Write Response to host
    assign bvalid = (aresetn == 1'b1) ? i_write_resp_valid : 1'b0;
    assign bresp  = 2'b00; // OKAY response 
    assign o_write_resp_ready = (aresetn == 1'b1) ? bready : 1'b0;

endmodule 