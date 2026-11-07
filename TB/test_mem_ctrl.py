import random
import itertools
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, with_timeout
from cocotb.utils import get_sim_time
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

from cocotb.utils import get_sim_time
from collections import Counter

# ----------------------------------------------------------------------
# Helpers for raw (master-less) AXI-Lite driving
# ----------------------------------------------------------------------
def v(sig):
    """int value of a signal, or -1 if it contains X/Z."""
    try:
        return int(sig.value)
    except ValueError:
        return -1


async def hit_counter(dut, box):
    while True:
        await RisingEdge(dut.clk)
        if v(dut.arvalid) == 1 and v(dut.arready) == 1 and v(dut.pb_hit) == 1:
            box[0] += 1


async def do_reset(dut, cycles=3):
    for s in ("awvalid", "wvalid", "bready", "arvalid", "rready"):
        getattr(dut, s).value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, cycles)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def raw_init(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    cocotb.start_soon(dram_model(dut))
    dut.awaddr.value = 0
    dut.wdata.value = 0
    dut.wstrb.value = 0xF
    dut.araddr.value = 0
    await do_reset(dut)


async def _ar_hs(dut, check_idle=False):
    for _ in range(500):
        await RisingEdge(dut.clk)
        if check_idle:
            assert v(dut.rvalid) == 0, "rvalid asserted before AR handshake"
        if v(dut.arready) == 1:
            dut.arvalid.value = 0
            return
    assert False, "timeout waiting for arready"


async def raw_ar(dut, addr):
    dut.araddr.value = addr
    dut.arvalid.value = 1
    await _ar_hs(dut, check_idle=True)


async def raw_r(dut, hold=0):
    dut.rready.value = 0
    for _ in range(500):
        await RisingEdge(dut.clk)
        if v(dut.rvalid) == 1:
            break
    else:
        assert False, "timeout waiting for rvalid"
    first = v(dut.rdata)
    for _ in range(hold):
        await RisingEdge(dut.clk)
        assert v(dut.rvalid) == 1, "rvalid dropped before rready"
        assert v(dut.rdata) == first, "rdata changed while stalled"
    dut.rready.value = 1
    await RisingEdge(dut.clk)
    assert v(dut.rvalid) == 1
    assert v(dut.rresp) == 0, "rresp not OKAY"
    data = v(dut.rdata)
    dut.rready.value = 0
    return data


async def raw_b(dut, hold=0):
    dut.bready.value = 0
    for _ in range(500):
        await RisingEdge(dut.clk)
        if v(dut.bvalid) == 1:
            break
    else:
        assert False, "timeout waiting for bvalid"
    for _ in range(hold):
        await RisingEdge(dut.clk)
        assert v(dut.bvalid) == 1, "bvalid dropped before bready"
    dut.bready.value = 1
    await RisingEdge(dut.clk)
    assert v(dut.bvalid) == 1
    assert v(dut.bresp) == 0, "bresp not OKAY"
    dut.bready.value = 0


async def raw_read(dut, addr, hold=0):
    await raw_ar(dut, addr)
    return await raw_r(dut, hold)


async def raw_write(dut, addr, data, strb=0xF, aw_delay=0, w_delay=0, bhold=0):
    async def aw():
        for _ in range(aw_delay):
            await RisingEdge(dut.clk)
        dut.awaddr.value = addr
        dut.awvalid.value = 1
        for _ in range(500):
            await RisingEdge(dut.clk)
            assert v(dut.bvalid) == 0, "bvalid before AW/W handshake"
            if v(dut.awready) == 1:
                dut.awvalid.value = 0
                return
        assert False, "timeout waiting for awready"

    async def w():
        for _ in range(w_delay):
            await RisingEdge(dut.clk)
        dut.wdata.value = data
        dut.wstrb.value = strb
        dut.wvalid.value = 1
        for _ in range(500):
            await RisingEdge(dut.clk)
            assert v(dut.bvalid) == 0, "bvalid before AW/W handshake"
            if v(dut.wready) == 1:
                dut.wvalid.value = 0
                return
        assert False, "timeout waiting for wready"

    t1 = cocotb.start_soon(aw())
    t2 = cocotb.start_soon(w())
    await t1
    await t2
    await raw_b(dut, bhold)


async def timed_read(m, g, addr):
    exp = g.read_memory(addr)
    t0 = get_sim_time("ns")
    raw = await with_timeout(cocotb.start_soon(m.read(addr, 4)), TIMEOUT_US, "us")
    lat = (get_sim_time("ns") - t0) / 10          # clock cycles (10 ns clock)
    got = int.from_bytes(raw.data, "little")
    assert got == exp, f"Mismatch @ {hex(addr)}: RTL={hex(got)} Golden={hex(exp)}"
    return lat


# ----------------------------------------------------------------------
# E. Timing / latency (3 tests)
# ----------------------------------------------------------------------
@cocotb.test()
async def test_t01_pb_hit_faster_than_miss(dut):
    m, g = await setup(dut)
    hits = [0]
    cocotb.start_soon(hit_counter(dut, hits))
    for i in range(12):
        await wr(m, g, 0x1000 + 4 * i, 0xA000 + i)
    lats = []
    for i in range(12):
        lats.append(await timed_read(m, g, 0x1000 + 4 * i))
        await ClockCycles(dut.clk, 30)            # let the prefetch complete
    dut._log.info(f"read latencies (cycles): {lats}   PB hits: {hits[0]}")
    assert hits[0] > 0, "prefetcher never produced a buffer hit"
    assert min(lats[4:]) < lats[0], f"PB hit not faster than a DRAM read: {lats}"


@cocotb.test()
async def test_t02_latency_bounds(dut):
    m, g = await setup(dut)
    rng = random.Random(7)
    for _ in range(20):
        a = (rng.randrange(0x10, 0x3F) << 8) | (rng.randrange(0, 64) << 2)
        lat = await timed_read(m, g, a)
        assert 4 <= lat <= 80, f"read @ {hex(a)} latency {lat} cycles out of bounds"
        await ClockCycles(dut.clk, 25)


@cocotb.test()
async def test_t03_row_hit_faster_than_row_miss(dut):
    m, g = await setup(dut)
    await timed_read(m, g, 0x1000)                # opens row 0x10
    await ClockCycles(dut.clk, 20)
    hit = await timed_read(m, g, 0x1010)          # same row
    await ClockCycles(dut.clk, 20)
    await timed_read(m, g, 0x1004)                # breaks the stride pattern
    await ClockCycles(dut.clk, 20)
    miss = await timed_read(m, g, 0x5000)         # different row
    dut._log.info(f"row hit = {hit} cycles, row miss = {miss} cycles")
    assert hit < miss, f"row hit ({hit}) not faster than row miss ({miss})"


# ----------------------------------------------------------------------
# F. Multiple outstanding transactions (2 tests)
# ----------------------------------------------------------------------
@cocotb.test()
async def test_t04_second_read_blocked_until_first_response_taken(dut):
    await raw_init(dut)
    A, B, DA, DB = 0x1000, 0x2000, 0xAAAA0001, 0xBBBB0002
    await raw_write(dut, A, DA)
    await raw_write(dut, B, DB)

    await raw_ar(dut, A)                          # first read accepted
    dut.araddr.value = B                          # second AR presented immediately
    dut.arvalid.value = 1
    for _ in range(10):                           # rready is low: R(A) pending
        await RisingEdge(dut.clk)
        assert v(dut.arready) == 0, "second AR accepted while first R still pending"

    assert await raw_r(dut) == DA                 # take R(A) -> unblocks B
    await _ar_hs(dut)
    assert await raw_r(dut) == DB


@cocotb.test()
async def test_t05_concurrent_read_and_write(dut):
    await raw_init(dut)
    await raw_write(dut, 0x1000, 0xAAAA5555)
    for i in range(20):
        b = 0x2000 + 4 * i
        w = cocotb.start_soon(raw_write(dut, b, 0x1000 + i))
        r = cocotb.start_soon(raw_read(dut, 0x1000))
        got = await r
        await w
        assert got == 0xAAAA5555, f"iter {i}: concurrent read returned {hex(got)}"
        assert await raw_read(dut, b) == 0x1000 + i


# ----------------------------------------------------------------------
# G. AW / W arrival order (3 x 3 = 9 tests)
# ----------------------------------------------------------------------
@cocotb.test()
@cocotb.parametrize(aw_delay=[0, 3, 6], w_delay=[0, 3, 6])
async def test_aw_w_skew(dut, aw_delay, w_delay):
    await raw_init(dut)
    for i in range(4):
        a, d = 0x1000 + 4 * i, 0xD0000000 + i
        await raw_write(dut, a, d, aw_delay=aw_delay, w_delay=w_delay, bhold=i)
        assert await raw_read(dut, a, hold=i) == d


# ----------------------------------------------------------------------
# H. Byte strobes, alignment, response codes (3 tests)
# ----------------------------------------------------------------------
@cocotb.test(expect_fail=True)
async def test_wstrb_partial_write_not_implemented(dut):
    """EXPECTED TO FAIL: o_write_req_strb is unconnected in top.sv, so wstrb is ignored."""
    await raw_init(dut)
    await raw_write(dut, 0x1000, 0x11223344)
    await raw_write(dut, 0x1000, 0xAABBCCDD, strb=0b0001)
    assert await raw_read(dut, 0x1000) == 0x112233DD


@cocotb.test()
async def test_unaligned_addresses_do_not_corrupt_neighbours(dut):
    await raw_init(dut)
    await raw_write(dut, 0x1000, 0x11111111)
    await raw_write(dut, 0x1004, 0x44444444)
    extra = {1: 0xA1A1A1A1, 2: 0xB2B2B2B2, 3: 0xC3C3C3C3}
    for off, val in extra.items():
        await raw_write(dut, 0x1000 + off, val)
    assert await raw_read(dut, 0x1000) == 0x11111111
    assert await raw_read(dut, 0x1004) == 0x44444444
    for off, val in extra.items():
        assert await raw_read(dut, 0x1000 + off) == val


@cocotb.test()
async def test_responses_are_okay(dut):
    m, g = await setup(dut)
    for i in range(10):
        a = 0x1000 + 4 * i
        g.write_memory(a, i)
        res = await with_timeout(cocotb.start_soon(m.write(a, i.to_bytes(4, "little"))), TIMEOUT_US, "us")
        assert int(getattr(res, "resp", 0)) == 0, f"bresp not OKAY at {hex(a)}"
        res = await with_timeout(cocotb.start_soon(m.read(a, 4)), TIMEOUT_US, "us")
        assert int(getattr(res, "resp", 0)) == 0, f"rresp not OKAY at {hex(a)}"


# ----------------------------------------------------------------------
# I. Reset behaviour (5 + 5 + 1 = 11 tests)
# ----------------------------------------------------------------------
@cocotb.test()
@cocotb.parametrize(delay=[0, 1, 2, 5, 10])
async def test_reset_during_read(dut, delay):
    await raw_init(dut)
    await raw_write(dut, 0x1000, 0xFEEDF00D)
    await raw_ar(dut, 0x1000)                     # read accepted, response not yet taken
    if delay:
        await ClockCycles(dut.clk, delay)
    await do_reset(dut)
    for _ in range(20):
        await RisingEdge(dut.clk)
        assert v(dut.rvalid) == 0 and v(dut.bvalid) == 0, "stale response after reset"
    assert await raw_read(dut, 0x1000) == 0xFEEDF00D        # DRAM contents retained
    await raw_write(dut, 0x1004, 0x1234ABCD)
    assert await raw_read(dut, 0x1004) == 0x1234ABCD


@cocotb.test()
@cocotb.parametrize(delay=[0, 1, 2, 5, 10])
async def test_reset_during_write(dut, delay):
    await raw_init(dut)
    # issue write without waiting for B, then reset
    dut.awaddr.value, dut.awvalid.value = 0x1000, 1
    dut.wdata.value, dut.wstrb.value, dut.wvalid.value = 0xBADC0FFE, 0xF, 1
    for _ in range(50):
        await RisingEdge(dut.clk)
        if v(dut.awready) == 1:
            break
    dut.awvalid.value = 0
    dut.wvalid.value = 0
    if delay:
        await ClockCycles(dut.clk, delay)
    await do_reset(dut)
    for _ in range(20):
        await RisingEdge(dut.clk)
        assert v(dut.rvalid) == 0 and v(dut.bvalid) == 0, "stale response after reset"
    await raw_write(dut, 0x2000, 0x13572468)       # interrupted write's result is undefined
    assert await raw_read(dut, 0x2000) == 0x13572468


@cocotb.test()
async def test_outputs_clean_after_reset(dut):
    await raw_init(dut)
    for n in ("awready", "wready", "arready", "rvalid", "bvalid", "o_dram_cmd"):
        assert v(getattr(dut, n)) != -1, f"{n} is X/Z after reset"
    assert v(dut.rvalid) == 0 and v(dut.bvalid) == 0


# ----------------------------------------------------------------------
# J. Raw-protocol fuzz: random AW/W skew, random stalls, 5 x 200 txns (5 tests)
# ----------------------------------------------------------------------
@cocotb.test()
@cocotb.parametrize(seed=list(range(5)))
async def test_raw_fuzz(dut, seed):
    await raw_init(dut)
    rng = random.Random(1000 + seed)
    exp = {}
    addrs = [0x1000 + 0x100 * r + 4 * c for r in range(3) for c in range(8)]
    idx = 0
    for n in range(200):
        idx = (idx + 1) % len(addrs) if rng.random() < 0.5 else rng.randrange(len(addrs))
        a = addrs[idx]
        if rng.random() < 0.45:
            d = rng.getrandbits(32)
            await raw_write(dut, a, d,
                            aw_delay=rng.randrange(0, 4), w_delay=rng.randrange(0, 4),
                            bhold=rng.randrange(0, 4))
            exp[a] = d
        else:
            got = await raw_read(dut, a, hold=rng.randrange(0, 4))
            assert got == exp.get(a, 0), f"seed {seed} txn {n} @ {hex(a)}: got {hex(got)} exp {hex(exp.get(a, 0))}"
        if rng.random() < 0.1:
            await ClockCycles(dut.clk, rng.randrange(1, 20))

# ----------------------------------------------------------------------
# A. Directed tests (20)
# ----------------------------------------------------------------------
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


# ----------------------------------------------------------------------
# B. Stride sweep: 8 strides x 5 lengths = 40 tests
# ----------------------------------------------------------------------
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


# ----------------------------------------------------------------------
# C. Data patterns: 10 tests
# ----------------------------------------------------------------------
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


# ----------------------------------------------------------------------
# D. Constrained-random mixes: 30 seeds
# ----------------------------------------------------------------------
@cocotb.test()
@cocotb.parametrize(seed=list(range(30)))
async def test_random_mix(dut, seed):
    m, g = await setup(dut)
    rng = random.Random(seed)
    rows = [0x1000, 0x2000, 0x3000]
    cur = rng.choice(rows)
    for _ in range(40):
        if rng.random() < 0.4:
            cur += 4
        else:
            cur = rng.choice(rows) + rng.randrange(0, 64) * 4
        if rng.random() < 0.4:
            await wr(m, g, cur, rng.getrandbits(32))
        else:
            await rd(m, g, cur)

N_SEEDS = 100
TXNS_PER_SEED = 100         # 100 x 100 = 10,000 transactions

TOTAL = Counter()             # accumulated across all seeds


async def monitor(dut, stats):
    """Coverage + AXI protocol checks, sampled every clock."""
    prev_rvalid = prev_rready = prev_bvalid = prev_bready = 0
    while True:
        await RisingEdge(dut.clk)
        if not dut.rst_n.value.is_resolvable or int(dut.rst_n.value) == 0:
            prev_rvalid = prev_rready = prev_bvalid = prev_bready = 0
            continue
        try:
            arv, arr = int(dut.arvalid.value), int(dut.arready.value)
            rv, rr = int(dut.rvalid.value), int(dut.rready.value)
            bv, br = int(dut.bvalid.value), int(dut.bready.value)
            pbh = int(dut.pb_hit.value)
            cmd = int(dut.o_dram_cmd.value)
        except ValueError:
            continue

        if arv and arr:
            stats["ar_accepted"] += 1
            if pbh:
                stats["pb_hits"] += 1
        stats[{1: "dram_ACT", 2: "dram_RD", 3: "dram_WR", 4: "dram_PRE"}.get(cmd, "dram_other")] += 1

        if prev_rvalid and not prev_rready and not rv:
            stats["PROTO_VIOLATION_rvalid_dropped"] += 1
        if prev_bvalid and not prev_bready and not bv:
            stats["PROTO_VIOLATION_bvalid_dropped"] += 1
        prev_rvalid, prev_rready, prev_bvalid, prev_bready = rv, rr, bv, br


def pick_op(rng, st):
    """Returns (is_write, addr) using weighted scenario selection."""
    r = rng.random()
    rows = [0x1000, 0x2000, 0x3000, 0x4000, 0x8000, 0x10000, 0x20000, 0x3F0000]
    if r < 0.30 and st["stride"]:                      # continue current stream
        st["cur"] += st["stride"]
        return rng.random() < 0.15, st["cur"]
    if r < 0.45:                                       # start new stride stream
        st["stride"] = rng.choice([4, 8, 12, 16, 32, 64, -4, -8])
        st["cur"] = rng.choice(rows) + rng.randrange(64, 128) * 4
        return False, st["cur"]
    if r < 0.60 and st["stride"]:                      # HAZARD: write to predicted next addr
        return True, st["cur"] + st["stride"]
    if r < 0.75:                                       # row thrash
        return rng.random() < 0.5, rng.choice(rows) + rng.randrange(0, 8) * 4
    if r < 0.85:                                       # re-access recent address
        return rng.random() < 0.3, st["cur"]
    return rng.random() < 0.4, rng.choice(rows) + rng.randrange(0, 64) * 4


@cocotb.test()
@cocotb.parametrize(seed=list(range(N_SEEDS)))
async def test_random_10k(dut, seed):
    m, g = await setup(dut)
    stats = Counter()
    cocotb.start_soon(monitor(dut, stats))

    if seed % 2:
        m.read_if.r_channel.set_pause_generator(itertools.cycle([1, 0, 0, 1, 1, 0]))
        m.write_if.b_channel.set_pause_generator(itertools.cycle([0, 1, 0, 0, 1]))

    rng = random.Random(seed)
    st = {"cur": 0x1000, "stride": 0}
    mismatches, shown = 0, 0

    for n in range(TXNS_PER_SEED):
        is_wr, addr = pick_op(rng, st)
        addr = (addr & 0x3FFFFC)
        if is_wr:
            data = rng.getrandbits(32)
            await wr(m, g, addr, data)
            stats["writes"] += 1
        else:
            exp = g.read_memory(addr)
            raw = await with_timeout(cocotb.start_soon(m.read(addr, 4)), TIMEOUT_US, "us")
            got = int.from_bytes(raw.data, "little")
            stats["reads"] += 1
            if got != exp:
                mismatches += 1
                if shown < 10:
                    dut._log.error(f"seed={seed} txn={n} MISMATCH @ {hex(addr)} RTL={hex(got)} GOLD={hex(exp)}")
                    shown += 1

        if rng.random() < 0.05:
            await ClockCycles(dut.clk, rng.randrange(1, 30))

    stats["mismatches"] = mismatches
    TOTAL.update(stats)
    dut._log.info(f"[seed {seed}] {dict(stats)}")
    if seed == N_SEEDS - 1:
        dut._log.info("=" * 60)
        dut._log.info(f"TOTAL TXNS      : {TOTAL['reads'] + TOTAL['writes']}")
        dut._log.info(f"READS CHECKED   : {TOTAL['reads']}   MISMATCHES: {TOTAL['mismatches']}")
        dut._log.info(f"PB HITS         : {TOTAL['pb_hits']} / {TOTAL['ar_accepted']} reads")
        dut._log.info(f"DRAM CMDS       : ACT={TOTAL['dram_ACT']} PRE={TOTAL['dram_PRE']} "
                      f"RD={TOTAL['dram_RD']} WR={TOTAL['dram_WR']}")
        dut._log.info(f"PROTOCOL VIOL.  : rvalid={TOTAL['PROTO_VIOLATION_rvalid_dropped']} "
                      f"bvalid={TOTAL['PROTO_VIOLATION_bvalid_dropped']}")
        dut._log.info("=" * 60)

    assert mismatches == 0, f"{mismatches} data mismatches in seed {seed}"
    assert stats["PROTO_VIOLATION_rvalid_dropped"] == 0
    assert stats["PROTO_VIOLATION_bvalid_dropped"] == 0