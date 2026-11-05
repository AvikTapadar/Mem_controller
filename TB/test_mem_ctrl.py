import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from cocotbext.axi import AxiLiteMaster, AxiLiteBus
from Golden_model import GoldenMemoryController

@cocotb.test()
async def test_sequential_reads(dut):
    """Test standard AXI reads and verify Stride Prefetcher behavior."""
    
    # Generate a 100MHz clock
    cocotb.start_soon(Clock(dut.aclk, 10, units="ns").start())
    
    # Initialize Golden Model and AXI Master Driver
    golden_model = GoldenMemoryController()
    axi_master = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi"), dut.aclk, dut.aresetn)

    # Reset RTL
    dut.aresetn.value = 0
    await RisingEdge(dut.aclk)
    await RisingEdge(dut.aclk)
    dut.aresetn.value = 1
    await RisingEdge(dut.aclk)

    # 1. Pre-load some data into the Golden Model and RTL (via AXI Writes)
    base_addr = 0x1000
    for i in range(5):
        addr = base_addr + (i * 4)
        data = 0xDEADBEEF + i
        
        # Update Golden Model
        golden_model.write_memory(addr, data)
        # Drive RTL
        await axi_master.write(addr, data.to_bytes(4, 'little'))

    # 2. Issue Sequential Reads to trigger the Prefetcher
    for i in range(5):
        addr = base_addr + (i * 4)
        
        # Get expected data from Golden Model
        expected_data = golden_model.read_memory(addr)
        
        # Read from RTL
        rtl_data_raw = await axi_master.read(addr, 4)
        rtl_data = int.from_bytes(rtl_data_raw.data, 'little')

        # Assert RTL matches Python
        assert rtl_data == expected_data, f"Data mismatch at {hex(addr)}: RTL={hex(rtl_data)}, Golden={hex(expected_data)}"
        
        cocotb.log.info(f"Read {hex(addr)} successfully. Data: {hex(rtl_data)}")

    # 3. Check RTL internal signals (Optional: Ensure PB hit actually occurred)
    # By the 4th read, confidence is high, and PB should serve the hit in 1 cycle
    pb_hit = dut.pb_hit.value
    cocotb.log.info(f"Final PB Hit Status: {pb_hit}")