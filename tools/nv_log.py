"""Log NV read helper calls (0x127b714: item, status) during a cold boot."""
import sys, json, collections
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
from emulator import run, ROOT
reads = collections.OrderedDict()
def setup(u, state):
    def enter(u, a, s, _):
        cmd = u.reg_read(UC_ARM_REG_R0)
        item = int.from_bytes(u.mem_read(cmd + 4, 2), 'little'); flag = int.from_bytes(u.mem_read(cmd + 6, 2), 'little')
        k = (item, flag, hex(u.reg_read(UC_ARM_REG_LR)))
        reads[k] = reads.get(k, 0) + 1
    u.hook_add(UC_HOOK_CODE, enter, begin=0x10d219a, end=0x10d219a)
state = run('amss', True, int(float(sys.argv[1])), True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True, keypad=True,
            nand_checkpoint=str(ROOT / 'analysis/nand_installed.zip'), debug_setup=setup, fast=True, uim_card=True, flip='open')
for k, v in reads.items(): print(v, k)
print("stop", state["stop"], state["instructions"], len(reads))
