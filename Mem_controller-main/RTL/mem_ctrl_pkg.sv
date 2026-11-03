package mem_ctrl_pkg;
    // System Parameters
    parameter ADDR_WIDTH = 32;
    parameter DATA_WIDTH = 32; 
    parameter STRB_WIDTH = DATA_WIDTH / 8;
    
    // Prefetch Buffer Parameters
    parameter PB_DEPTH = 16;
    parameter PB_INDEX_WIDTH = $clog2(PB_DEPTH);
    
    // DRAM State Machine Encodings
    typedef enum logic [2:0] {
        DRAM_IDLE  = 3'b000,
        DRAM_ACT   = 3'b001,
        DRAM_READ  = 3'b010,
        DRAM_WRITE = 3'b011,
        DRAM_PRE   = 3'b100
    } dram_state_t;

    // Transaction Types for Arbiter
    typedef enum logic [1:0] {
        REQ_DEMAND_READ  = 2'b00,
        REQ_DEMAND_WRITE = 2'b01,
        REQ_PREFETCH     = 2'b10
    } req_type_t;
endpackage