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

from collections import Counter

N_SEEDS = 1000
TXNS_PER_SEED = 10          # 10 x 1000 = 10,000 transactions

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

        # ---- coverage ----
        if arv and arr:
            stats["ar_accepted"] += 1
            if pbh:
                stats["pb_hits"] += 1
        stats[{1: "dram_ACT", 2: "dram_RD", 3: "dram_WR", 4: "dram_PRE"}.get(cmd, "dram_other")] += 1

        # ---- AXI protocol rules ----
        # valid must stay high until the ready handshake happens
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
async def test_random(dut, seed):
    m, g = await setup(dut)
    stats = Counter()
    cocotb.start_soon(monitor(dut, stats))

    # random backpressure on responses for half the seeds
    if seed % 2:
        m.read_if.r_channel.set_pause_generator(itertools.cycle([1, 0, 0, 1, 1, 0]))
        m.write_if.b_channel.set_pause_generator(itertools.cycle([0, 1, 0, 0, 1]))

    rng = random.Random(seed)
    st = {"cur": 0x1000, "stride": 0}
    mismatches, shown = 0, 0

    for n in range(TXNS_PER_SEED):
        is_wr, addr = pick_op(rng, st)
        addr = (addr & 0x3FFFFC)                        # keep inside 4 MB, word aligned
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

        if rng.random() < 0.05:                         # occasional idle gap
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