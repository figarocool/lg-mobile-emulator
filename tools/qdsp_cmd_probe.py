"""Log every command the ARM driver pushes to the QDSP (function 0x1267874)."""
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_PC
from emulator import run, ROOT
log = []
def setup(u, state):
    def cmd(u, a, s, _):
        r0, r1, r2 = (u.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
        n = int.from_bytes(u.mem_read(r2, 2), 'little')
        words = [int.from_bytes(u.mem_read(r2 + 2 * i, 2), 'little') for i in range(1, min(n, 12))]
        reg = int.from_bytes(u.mem_read(r0, 2), 'little') if 0x50000000 <= r0 < 0x60000000 else None
        log.append((hex(r0), hex(r1), n, [hex(w) for w in words], reg))
    u.hook_add(UC_HOOK_CODE, cmd, begin=0x1267874, end=0x1267874)
run('amss', True, 450000000, True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True, keypad=True,
    resume=ROOT/'analysis/nopin1.zip', debug_setup=setup, fast=True, press=[(2, 1)], uim_card=True, flip='open')
seen=[]
for e in log:
    k=(e[0],e[1],tuple(e[3]))
    if k not in seen: seen.append(k); print(e)
