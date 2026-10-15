"""Force ONLINE in a checkpoint copy and list rex_set_sigs calls: current task -> target task, signal, caller."""
import sys, collections
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
from emulator import run, ROOT
from task_stack import load, tasks
mode = int(sys.argv[1]); limit = int(float(sys.argv[2])); src = sys.argv[3] if len(sys.argv) > 3 else 'analysis/cold_net.zip'
names = {a: n for n, a, _, _ in tasks(load(str(ROOT / src)))}
seen = collections.OrderedDict()
def setup(u, state):
    for reg, v in ((UC_ARM_REG_R0, 0), (UC_ARM_REG_R1, 0), (UC_ARM_REG_R2, 0xffffffff), (UC_ARM_REG_R3, mode),
                   (UC_ARM_REG_LR, 0x4f01001), (UC_ARM_REG_PC, 0xd1a449)):
        u.reg_write(reg, v)
    u.mem_write(0x4f01000, b'\x00\xbf\x00\xbf')
    stage = {'n': 0}
    def chain(u, a, s, _):
        if stage['n'] == 0:
            stage['n'] = 1
            sp = u.reg_read(UC_ARM_REG_SP) - 16
            u.mem_write(sp, (1).to_bytes(4, 'little')); u.reg_write(UC_ARM_REG_SP, sp)
            for reg, v in ((UC_ARM_REG_R0, 0), (UC_ARM_REG_R1, 0), (UC_ARM_REG_R2, 0), (UC_ARM_REG_R3, 0),
                           (UC_ARM_REG_LR, 0x4f01001), (UC_ARM_REG_PC, 0xd1a7a7)):
                u.reg_write(reg, v)
    u.hook_add(UC_HOOK_CODE, chain, begin=0x4f01000, end=0x4f01000)
    def sig(u, a, s, _):
        cur = names.get(int.from_bytes(u.mem_read(0x19a3f18, 4), 'little'), '?')
        key = (cur, names.get(u.reg_read(UC_ARM_REG_R0), hex(u.reg_read(UC_ARM_REG_R0))), hex(u.reg_read(UC_ARM_REG_R1)), hex(u.reg_read(UC_ARM_REG_LR)))
        seen[key] = seen.get(key, 0) + 1
    u.hook_add(UC_HOOK_CODE, sig, begin=0x1265da8, end=0x1265da8)
state = run('amss', True, limit, True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True, keypad=True,
    resume=ROOT / src, debug_setup=setup, fast=True, uim_card=True, flip='open')
for k, v in seen.items():
    if k[1] not in ('UIM', 'SLEEP', 'GRAPH') and k[0] not in ('SLEEP',): print(v, k)
ua = state.get('uim_uart') or {}
print({k: (v if not isinstance(v, list) else len(v)) for k, v in ua.items()})
for a in (ua.get('apdus_tail') or [])[-25:]: print(a)
