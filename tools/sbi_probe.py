"""Show the peripheral registers the ARM polls just before the firmware reports an SBI timeout."""
from collections import deque
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC
from emulator import run, ROOT
last = deque(maxlen=400); out = []
def setup(u, state):
    def rd(u, access, a, size, value, _):
        if a in (0x60000024, 0x84000d2c): return
        last.append(('r' if access == 0 else 'w', hex(a), size, hex(value & 0xffffffff) if access else '', hex(u.reg_read(UC_ARM_REG_PC))))
    for lo, hi in ((0x30000000, 0x3fffffff), (0x48000000, 0x4fffffff), (0x60000000, 0x6fffffff), (0x80000000, 0x8fffffff)):
        u.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, rd, begin=lo, end=hi)
    def msg(u, a, s, _):
        if len(out) < 2: out.append(list(last))
    u.hook_add(UC_HOOK_CODE, msg, begin=0x1278f50, end=0x1278f50)
run('amss', True, 450000000, True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True, keypad=True,
    resume=ROOT/'analysis/nopin1.zip', debug_setup=setup, fast=True, press=[(2, 1)], uim_card=True, flip='open')
for blk in out[:1]:
    for e in blk[-40:]: print(e)
