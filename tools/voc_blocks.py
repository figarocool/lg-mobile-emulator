"""List the functions called after the firmware prints 'TONE:' (where the tone leaves the SND task)."""
import sys
from unicorn import UC_HOOK_CODE, UC_HOOK_BLOCK
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_LR
from emulator import run, ROOT

calls = []
def setup(u, state):
    armed = {'on': False}
    def msg(u, a, s, _):
        try:
            p = int.from_bytes(u.mem_read(u.reg_read(UC_ARM_REG_R0)+8, 4), 'little')
            t = bytes(u.mem_read(p, 24)).split(b'\0')[0]
        except Exception:
            return
        if t.startswith(b'TONE:'): armed['on'] = True
        calls.append(('msg', t.decode('latin1'), hex(u.reg_read(UC_ARM_REG_LR))) if armed['on'] else None)
    def blk(u, a, s, _):
        if armed['on'] and len(calls) < 3000: calls.append(('blk', hex(a)))
    for a in (0xeee1fc, 0xeee210, 0x7c0654, 0xb8f47c, 0x12dd490, 0x12dd484, 0x7c07dc):
        u.hook_add(UC_HOOK_CODE, msg, begin=a, end=a)
    u.hook_add(UC_HOOK_BLOCK, blk, begin=0x1260000, end=0x1270000)
s = run('amss', True, 450000000, True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True,
        keypad=True, resume=ROOT/'analysis/nopin1.zip', debug_setup=setup, fast=True, press=[(2, 1)], uim_card=True, flip="open")
seen = []
for c in calls:
    if c and c not in seen: seen.append(c)
for c in seen[:400]: print(c)
