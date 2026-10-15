"""Census of every access to the hardware windows, including pages the emulator maps directly."""
import json, sys, collections
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_READ
from unicorn.arm_const import UC_ARM_REG_PC
from emulator import run, ROOT

WINDOWS = [(0x30000000, 0x30100000), (0x48000000, 0x48100000), (0x50000000, 0x5a000000),
           (0x60000000, 0x64000000), (0x80000000, 0x80100000), (0x84000000, 0x84100000)]
census = collections.Counter()


def setup(u, state):
    def hook(u, access, address, size, value, _):
        census[(hex(address), 'r' if access == UC_MEM_READ else 'w', hex(u.reg_read(UC_ARM_REG_PC)))] += 1
    for lo, hi in WINDOWS:
        u.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, hook, begin=lo, end=hi - 1)


run('amss', True, int(sys.argv[2]), True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True,
    keypad=True, uim_card=True, fast=True, resume=ROOT / sys.argv[1], debug_setup=setup)
by = collections.defaultdict(list)
for (a, o, pc), n in census.items():
    by[a].append((o, pc, n))
out = {a: sorted(v, key=lambda x: -x[2])[:3] for a, v in by.items()}
(ROOT / 'analysis/full_mmio.json').write_text(json.dumps(out, indent=1))
print(len(out))
