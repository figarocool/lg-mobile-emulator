"""Force ONLINE in a checkpoint copy and list the AMSS queue puts (q_put 0x1279116): queue, caller, first bytes of the item."""
import collections, sys
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
from emulator import run, ROOT
mode = int(sys.argv[1]); limit = int(float(sys.argv[2])); src = sys.argv[3] if len(sys.argv) > 3 else 'analysis/net_imei.zip'
puts = collections.OrderedDict()
def setup(u, state):
    for reg, v in ((UC_ARM_REG_R0, 0), (UC_ARM_REG_R1, 0), (UC_ARM_REG_R2, 0xffffffff), (UC_ARM_REG_R3, mode),
                   (UC_ARM_REG_LR, 0x4f01001), (UC_ARM_REG_PC, 0xd1a449)):
        u.reg_write(reg, v)
    u.mem_write(0x4f01000, b'\x00\xbf\x00\xbf')
    def qput(u, a, s, _):
        q, item, lr = u.reg_read(UC_ARM_REG_R0), u.reg_read(UC_ARM_REG_R1), u.reg_read(UC_ARM_REG_LR)
        try: data = bytes(u.mem_read(item, 32)).hex()
        except Exception: data = '?'
        e = puts.setdefault((hex(q), hex(lr)), [0, data])
        e[0] += 1
    u.hook_add(UC_HOOK_CODE, qput, begin=0x1279116, end=0x1279116)
run('amss', True, limit, True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True, keypad=True,
    resume=ROOT / src, debug_setup=setup, fast=True, uim_card=True, flip='open', imei='356938035643809', rf_defaults=True)
for k, v in puts.items(): print(k, v[0], v[1])
