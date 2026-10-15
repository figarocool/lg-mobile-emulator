"""Read-only log of REX signals sent to chosen tasks (rex_set_sigs at 0x1265dec; 0x1265da8 is rex_clr_sigs) and who sent them."""
from collections import deque
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_LR

SET_SIGS = 0x1265dec
TASKS = {0x1c03c54: 'UIM', 0x1c0b40c: 'GSDI', 0x1c0b5e8: 'GSTK', 0x1bf7628: 'UI', 0x1bf91bc: 'PS'}


def attach(uc, state):
    events = deque(maxlen=6000)
    state['rex_signal_watch'] = events

    def observe(u, address, size, _):
        tcb = u.reg_read(UC_ARM_REG_R0)
        if tcb in TASKS:
            events.append([TASKS[tcb], hex(u.reg_read(UC_ARM_REG_R1)), hex(u.reg_read(UC_ARM_REG_LR))])

    uc.hook_add(UC_HOOK_CODE, observe, begin=SET_SIGS, end=SET_SIGS)


def finalize(state):
    if 'rex_signal_watch' in state:
        state['rex_signal_watch'] = list(state['rex_signal_watch'])
