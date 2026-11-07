import random
import itertools
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, with_timeout
from cocotbext.axi import AxiLiteMaster, AxiLiteBus
from Golden_model import GoldenMemoryController

TIMEOUT_US = 5

async def dram_model(dut):
    """Behavioural DRAM driving i_dram_rdata from o_dram_* commands."""
    mem, row = {}, 0
    dut.i_dram_rdata.value = 0
    while True:
        await RisingEdge(dut.clk)
        cmd = dut.o_dram_cmd.value
        if not cmd.is_resolvable:
            continue
        cmd = int(cmd)
        a = int(dut.o_dram_addr.value)
        if cmd == 1:      # ACT
            row = a
        elif cmd == 3:    # WR
            mem[(row << 8) | (a & 0xFF)] = int(dut.o_dram_wdata.value)
        elif cmd == 2:    # RD
            dut.i_dram_rdata.value = mem.get((row << 8) | (a & 0xFF), 0)


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    cocotb.start_soon(dram_model(dut))
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)
    master = AxiLiteMaster(AxiLiteBus.from_prefix(dut, ""), dut.clk, dut.rst_n,
                           reset_active_level=False)
    return master, GoldenMemoryController()


async def wr(m, g, addr, data):
    g.write_memory(addr, data)
    await with_timeout(cocotb.start_soon(m.write(addr, data.to_bytes(4, "little"))),
                       TIMEOUT_US, "us")


async def rd(m, g, addr):
    exp = g.read_memory(addr)
    raw = await with_timeout(cocotb.start_soon(m.read(addr, 4)), TIMEOUT_US, "us")
    got = int.from_bytes(raw.data, "little")
    assert got == exp, f"Mismatch @ {hex(addr)}: RTL={hex(got)} Golden={hex(exp)}"
    return got

# A. Directed tests (20)
@cocotb.test()
async def test_01_single_write_read(dut):
    m, g = await setup(dut)
    await wr(m, g, 0x1000, 0xDEADBEEF)
    await rd(m, g, 0x1000)


@cocotb.test()
async def test_02_read_uninitialized_is_zero(dut):
    m, g = await setup(dut)
    await rd(m, g, 0x1040)


@cocotb.test()
async def test_03_overwrite_same_addr(dut):
    m, g = await setup(dut)
    await wr(m, g, 0x1000, 0x11111111)
    await wr(m, g, 0x1000, 0x22222222)
    await rd(m, g, 0x1000)


@cocotb.test()
async def test_04_all_zero_and_all_ones(dut):
    m, g = await setup(dut)
    await wr(m, g, 0x1000, 0x00000000)
    await wr(m, g, 0x1004, 0xFFFFFFFF)
    await rd(m, g, 0x1000)
    await rd(m, g, 0x1004)


@cocotb.test()
async def test_05_back_to_back_writes_then_reads(dut):
    m, g = await setup(dut)
    for i in range(8):
        await wr(m, g, 0x1000 + 4 * i, 0xA0000000 + i)
    for i in range(8):
        await rd(m, g, 0x1000 + 4 * i)


@cocotb.test()
async def test_06_read_immediately_after_write(dut):
    m, g = await setup(dut)
    for i in range(6):
        await wr(m, g, 0x1100 + 4 * i, 0xB0000000 + i)
        await rd(m, g, 0x1100 + 4 * i)


@cocotb.test()
async def test_07_row_hit_sequence(dut):
    m, g = await setup(dut)
    for i in range(10):
        await wr(m, g, 0x1000 + 4 * i, i * 0x01010101)
    for i in range(10):
        await rd(m, g, 0x1000 + 4 * i)


@cocotb.test()
async def test_08_row_miss_alternating(dut):
    m, g = await setup(dut)
    await wr(m, g, 0x1000, 0xAAAA0001)
    await wr(m, g, 0x2000, 0xBBBB0002)
    for _ in range(4):
        await rd(m, g, 0x1000)
        await rd(m, g, 0x2000)


@cocotb.test()
async def test_09_first_and_last_column_of_row(dut):
    m, g = await setup(dut)
    await wr(m, g, 0x1000, 0xC0000000)
    await wr(m, g, 0x10FC, 0xC00000FC)
    await rd(m, g, 0x1000)
    await rd(m, g, 0x10FC)


@cocotb.test()
async def test_10_row_boundary_crossing(dut):
    m, g = await setup(dut)
    for a in (0x10F8, 0x10FC, 0x1100, 0x1104):
        await wr(m, g, a, 0xD0000000 + a)
    for a in (0x10F8, 0x10FC, 0x1100, 0x1104):
        await rd(m, g, a)


@cocotb.test()
async def test_11_sixteen_distinct_rows(dut):
    m, g = await setup(dut)
    addrs = [0x1000 + 0x100 * i for i in range(16)]
    for a in addrs:
        await wr(m, g, a, 0xE0000000 + a)
    for a in addrs:
        await rd(m, g, a)


@cocotb.test()
async def test_12_interleaved_write_read(dut):
    m, g = await setup(dut)
    for i in range(10):
        a = 0x1000 + 4 * i
        await wr(m, g, a, 0xF0000000 + i)
        await rd(m, g, a)
        if i:
            await rd(m, g, a - 4)


@cocotb.test()
async def test_13_write_to_prefetched_address_not_stale(dut):
    m, g = await setup(dut)
    for i in range(8):
        await wr(m, g, 0x1000 + 4 * i, 0x1000 + i)
    for i in range(4):                       # train prefetcher
        await rd(m, g, 0x1000 + 4 * i)
    await wr(m, g, 0x1010, 0x600DF00D)       # overwrite predicted next addr
    await rd(m, g, 0x1010)


@cocotb.test()
async def test_14_reread_same_addr_many_times(dut):
    m, g = await setup(dut)
    await wr(m, g, 0x1234 & ~3, 0x12345678)
    for _ in range(12):
        await rd(m, g, 0x1234 & ~3)


@cocotb.test()
async def test_15_reverse_stride_reads(dut):
    m, g = await setup(dut)
    for i in range(8):
        await wr(m, g, 0x1000 + 4 * i, 0x70000000 + i)
    for i in reversed(range(8)):
        await rd(m, g, 0x1000 + 4 * i)


@cocotb.test()
async def test_16_long_sequential_stream_32(dut):
    m, g = await setup(dut)
    for i in range(32):
        await wr(m, g, 0x2000 + 4 * i, 0x80000000 + i)
    for i in range(32):
        await rd(m, g, 0x2000 + 4 * i)


@cocotb.test()
async def test_17_same_address_repeated_zero_stride(dut):
    m, g = await setup(dut)
    await wr(m, g, 0x1000, 0x99999999)
    for _ in range(10):
        await rd(m, g, 0x1000)


@cocotb.test()
async def test_18_backpressure_on_read_response(dut):
    m, g = await setup(dut)
    m.read_if.r_channel.set_pause_generator(itertools.cycle([1, 1, 1, 0]))
    for i in range(6):
        await wr(m, g, 0x1000 + 4 * i, 0x30000000 + i)
    for i in range(6):
        await rd(m, g, 0x1000 + 4 * i)


@cocotb.test()
async def test_19_backpressure_on_write_response(dut):
    m, g = await setup(dut)
    m.write_if.b_channel.set_pause_generator(itertools.cycle([1, 1, 1, 0]))
    for i in range(6):
        await wr(m, g, 0x1000 + 4 * i, 0x40000000 + i)
    for i in range(6):
        await rd(m, g, 0x1000 + 4 * i)


@cocotb.test()
async def test_20_idle_gaps_between_transactions(dut):
    m, g = await setup(dut)
    for i in range(5):
        await wr(m, g, 0x1000 + 4 * i, 0x50000000 + i)
        await ClockCycles(dut.clk, 20)
    for i in range(5):
        await rd(m, g, 0x1000 + 4 * i)
        await ClockCycles(dut.clk, 15)

# B. Stride sweep: 8 strides x 5 lengths = 40 tests
@cocotb.test()
@cocotb.parametrize(stride=[4, 8, 12, 16, 32, 64, 128, 256],
                    length=[2, 3, 4, 6, 10])
async def test_stride(dut, stride, length):
    m, g = await setup(dut)
    base = 0x1000
    addrs = [base + stride * i for i in range(length)]
    for i, a in enumerate(addrs):
        await wr(m, g, a, 0xC0DE0000 + i)
    for a in addrs:
        await rd(m, g, a)

# C. Data patterns: 10 tests
@cocotb.test()
@cocotb.parametrize(pattern=[0x00000000, 0x00000001, 0xFFFFFFFF, 0xAAAAAAAA,
                             0x55555555, 0x80000000, 0x7FFFFFFF, 0xDEADBEEF,
                             0x12345678, 0xCAFEBABE])
async def test_data_pattern(dut, pattern):
    m, g = await setup(dut)
    for a in (0x1000, 0x1004, 0x2000):
        await wr(m, g, a, pattern)
    for a in (0x1000, 0x1004, 0x2000):
        await rd(m, g, a)

# D. Constrained-random mixes: 30 seeds
@cocotb.test()
@cocotb.parametrize(seed=list(range(30)))
async def test_random_mix(dut, seed):
    m, g = await setup(dut)
    rng = random.Random(seed)
    rows = [0x1000, 0x2000, 0x3000]
    cur = rng.choice(rows)
    for _ in range(40):
        if rng.random() < 0.4:                        # continue a sequential stream
            cur += 4
        else:                                         # jump somewhere in a small pool
            cur = rng.choice(rows) + rng.randrange(0, 64) * 4
        if rng.random() < 0.4:
            await wr(m, g, cur, rng.getrandbits(32))
        else:
            await rd(m, g, cur)