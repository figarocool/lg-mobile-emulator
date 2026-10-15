"""Force ONLINE (cm_ph_cmd_oprt_mode) in a checkpoint copy and report how many blocks each REX task executed."""
import sys, collections, struct
from unicorn import UC_HOOK_CODE, UC_HOOK_BLOCK
from unicorn.arm_const import *
from emulator import run, ROOT
from task_stack import load, tasks
mode = int(sys.argv[1]); limit = int(float(sys.argv[2])) if len(sys.argv) > 2 else 600000000
src = sys.argv[3] if len(sys.argv) > 3 else 'analysis/cold_net.zip'
names = {a: n for n, a, _, _ in tasks(load(str(ROOT / src)))}
counts = collections.Counter()
def setup(u, state):
    for reg, v in ((UC_ARM_REG_R0, 0), (UC_ARM_REG_R1, 0), (UC_ARM_REG_R2, 0xffffffff), (UC_ARM_REG_R3, mode),
                   (UC_ARM_REG_LR, 0x4f01001), (UC_ARM_REG_PC, 0xd1a449)):
        u.reg_write(reg, v)
    u.mem_write(0x4f01000, b'\x00\xbf\x00\xbf')
    def blk(u, a, s, _):
        counts[names.get(int.from_bytes(u.mem_read(0x19a3f18, 4), 'little'), '?')] += 1
    u.hook_add(UC_HOOK_BLOCK, blk)
state = run('amss', True, limit, True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True, keypad=True,
            resume=ROOT / src, debug_setup=setup, fast=False, uim_card=True, flip='open', imei='356938035643809')
for n, c in counts.most_common(40): print(c, n)
