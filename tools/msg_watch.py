"""Read-only log of the firmware's own debug messages (msg struct pointer in r0, fmt at +8)."""
import os
from collections import deque
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_LR

SENDERS = (0x7c0654, 0xb8f47c, 0xeee1fc, 0x12dd490, 0x12dd484, 0xeee210, 0x7c07dc)


def attach(uc, state):
    if not os.environ.get('U310_MSG_WATCH'):
        return
    events = deque(maxlen=int(os.environ.get('U310_MSG_WATCH')))
    state['msg_watch'] = events

    def observe(u, address, size, _):
        try:
            struct_address = u.reg_read(UC_ARM_REG_R0)
            fmt = int.from_bytes(u.mem_read(struct_address + 8, 4), 'little')
            text = bytes(u.mem_read(fmt, 100)).split(b'\0')[0].decode('latin1')
            if not text or not all(32 <= ord(c) < 127 for c in text):
                return
            events.append([hex(u.reg_read(UC_ARM_REG_LR)), text, hex(u.reg_read(UC_ARM_REG_R1)),
                           hex(u.reg_read(UC_ARM_REG_R2)), hex(u.reg_read(UC_ARM_REG_R3))])
        except Exception:
            pass

    for address in SENDERS:
        uc.hook_add(UC_HOOK_CODE, observe, begin=address, end=address)


def finalize(state):
    if 'msg_watch' in state:
        state['msg_watch'] = list(state['msg_watch'])
