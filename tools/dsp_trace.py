"""Log writes to the DSP shared-memory windows during a run (diagnostic for the audio component)."""
import json, os, sys, collections
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_READ
from unicorn.arm_const import UC_ARM_REG_PC
from emulator import run, ROOT

WINDOWS = [(0x50000000, 0x5fffffff)]
events = []


def setup(u, state):
    def hook(u, access, address, size, value, _):
        pc = u.reg_read(UC_ARM_REG_PC)
        if pc not in (0x10d6f9a, 0x162b37e) and len(events) < 200000:  # skip the image copy loops
            events.append((state['instructions'], address, size, int.from_bytes(u.mem_read(address, 4), 'little') if access == UC_MEM_READ else value & 0xffffffff, pc, 'r' if access == UC_MEM_READ else 'w'))
    for lo, hi in WINDOWS:
        u.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, hook, begin=lo, end=hi)


os.environ.setdefault('U310_PIN', 'off')
press = [tuple(int(v) for v in sys.argv[3].split(','))] if len(sys.argv) > 3 else []
s = run('amss', True, int(sys.argv[2]), True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True,
        keypad=True, uim_card=True, fast=True, press=press, resume=ROOT / sys.argv[1], debug_setup=setup)
print(len(events))
(ROOT / 'analysis/dsp_trace.json').write_text(json.dumps(events))
