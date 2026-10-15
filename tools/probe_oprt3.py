"""Debugger-call cm_ph_cmd_subscription_available(gw_status) in a checkpoint copy and show what CM/SD/MMOC do."""
import sys, json
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
from emulator import run, ROOT
mode = int(sys.argv[1])
def setup(u, state):
    for reg, v in ((UC_ARM_REG_R0, 0), (UC_ARM_REG_R1, 0), (UC_ARM_REG_R2, 0xffffffff), (UC_ARM_REG_R3, mode),
                   (UC_ARM_REG_LR, 0x4f01001), (UC_ARM_REG_PC, 0xd1a449)):
        u.reg_write(reg, v)
    u.mem_write(0x4f01000, b'\x00\xbf\x00\xbf')
    def done(u, a, s, _):
        state['probe_return'] = hex(u.reg_read(UC_ARM_REG_R0))
    u.hook_add(UC_HOOK_CODE, done, begin=0x4f01000, end=0x4f01000)
state = run('amss', True, 1200000000, True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True, keypad=True,
    resume=ROOT/'analysis/net_imei.zip', debug_setup=setup, fast=True, uim_card=True, flip='open', imei='356938035643809', rf_defaults=True)
msgs = state.get('msg_watch', [])
j = [i for i,e in enumerate(msgs) if 'oprt_mode = ' in e[1]][0]
for e in msgs[-60:]:
    if not e[1].startswith(('MM_IV','[MMAPI','[DRM','free memory','Lo pri','OEM','[LGOEM','Timed out')): print(e[1], e[2:5])
print(state.get('probe_return'))
print(state.get('pc_hits'))
