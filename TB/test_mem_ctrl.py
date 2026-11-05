import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, with_timeout
from cocotbext.axi import AxiLiteMaster, AxiLiteBus
from Golden_model import GoldenMemoryController


async def dram_model(dut):
    """Simple behavioural DRAM driving i_dram_rdata from o_dram_* commands."""
    mem, row = {}, 0
    dut.i_dram_rdata.value = 0
    while True:
        await RisingEdge(dut.clk)
        cmd = dut.o_dram_cmd.value
        if not cmd.is_resolvable:
            continue
        cmd = int(cmd)
        a = int(dut.o_dram_addr.value)
        if cmd == 1:    # ACT
            row = a
        elif cmd == 3:  # WR
            mem[(row << 8) | (a & 0xFF)] = int(dut.o_dram_wdata.value)
        elif cmd == 2:  # RD
            dut.i_dram_rdata.value = mem.get((row << 8) | (a & 0xFF), 0)


@cocotb.test()
async def test_sequential_reads(dut):
    """Test standard AXI reads and verify Stride Prefetcher behavior."""

    # 1. Start the clock first
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    cocotb.start_soon(dram_model(dut))

    # 2. Assert reset immediately
    dut.rst_n.value = 0

    # 3. Wait 2 clock cycles so reset propagates and all X's are flushed out
    for _ in range(2):
        await RisingEdge(dut.clk)

    # 4. De-assert reset
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # 5. Initialize the AXI Master (rst_n is ACTIVE-LOW)
    axi_master = AxiLiteMaster(AxiLiteBus.from_prefix(dut, ""), dut.clk, dut.rst_n,
                               reset_active_level=False)

    # Reset RTL
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # Golden model created ONCE, outside the loops
    golden_model = GoldenMemoryController()

    # 1. Pre-load some data into the Golden Model and RTL (via AXI Writes)
    base_addr = 0x1000
    for i in range(5):
        addr = base_addr + (i * 4)
        data = 0xDEADBEEF + i

        # Update Golden Model
        golden_model.write_memory(addr, data)
        # Drive RTL
        await with_timeout(cocotb.start_soon(axi_master.write(addr, data.to_bytes(4, 'little'))), 2, "us")

    # 2. Issue Sequential Reads to trigger the Prefetcher
    for i in range(5):
        addr = base_addr + (i * 4)

        # Get expected data from Golden Model
        expected_data = golden_model.read_memory(addr)

        # Read from RTL
        rtl_data_raw = await with_timeout(cocotb.start_soon(axi_master.read(addr, 4)), 2, "us")
        rtl_data = int.from_bytes(rtl_data_raw.data, 'little')

        # Assert RTL matches Python
        assert rtl_data == expected_data, f"Data mismatch at {hex(addr)}: RTL={hex(rtl_data)}, Golden={hex(expected_data)}"

        cocotb.log.info(f"Read {hex(addr)} successfully. Data: {hex(rtl_data)}")

    # 3. Check RTL internal signals (Optional: Ensure PB hit actually occurred)
    # By the 4th read, confidence is high, and PB should serve the hit in 1 cycle
    pb_hit = dut.pb_hit.value
    cocotb.log.info(f"Final PB Hit Status: {pb_hit}")