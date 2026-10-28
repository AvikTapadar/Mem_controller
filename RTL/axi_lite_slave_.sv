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
    input logic rready

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
    // Accept address when valid and internal queue is ready
    assign s_axi_arready = i_read_req_ready;
    assign o_read_req_valid = s_axi_arvalid;
    assign o_read_req_addr  = s_axi_araddr;

    // Return data to host
    assign s_axi_rvalid = i_read_resp_valid;
    assign s_axi_rdata  = i_read_resp_data;
    assign s_axi_rresp  = 2'b00; // OKAY response
    assign o_read_resp_ready = s_axi_rready;

    // Write Channel Logic 
    // Requires both AW (Address) and W (Data) to be valid before sending to arbiter
    logic write_handshake_ready;
    assign write_handshake_ready = s_axi_awvalid && s_axi_wvalid && i_write_req_ready;

    assign s_axi_awready = write_handshake_ready;
    assign s_axi_wready  = write_handshake_ready;

    assign o_write_req_valid = s_axi_awvalid && s_axi_wvalid;
    assign o_write_req_addr  = s_axi_awaddr;
    assign o_write_req_data  = s_axi_wdata;
    assign o_write_req_strb  = s_axi_wstrb;

    // Write Response to host
    assign s_axi_bvalid = i_write_resp_valid;
    assign s_axi_bresp  = 2'b00; // OKAY response 
    assign o_write_resp_ready = s_axi_bready;

endmodule 