"""Read-only log of calls to chosen code addresses: U310_ENTRY_WATCH=0xaddr,0xaddr (r0, r1, lr)."""
import os
from collections import Counter
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_LR, UC_ARM_REG_SP


def attach(uc, state):
    spec = os.environ.get('U310_ENTRY_WATCH')
    if not spec:
        return
    seen = Counter()
    stacks = []
    state['entry_watch'] = seen
    state['entry_stacks'] = stacks

    def observe(u, address, size, _):
        seen[(hex(address), hex(u.reg_read(UC_ARM_REG_R0)), hex(u.reg_read(UC_ARM_REG_R1)),
              hex(u.reg_read(UC_ARM_REG_LR)))] += 1
        if os.environ.get('U310_ENTRY_STACK'):
            sp = u.reg_read(UC_ARM_REG_SP)
            stacks.append([hex(int.from_bytes(u.mem_read(sp + 4 * k, 4), 'little')) for k in range(64)])

    for item in spec.split(','):
        address = int(item, 16)
        uc.hook_add(UC_HOOK_CODE, observe, begin=address, end=address)


def finalize(state):
    if 'entry_watch' in state:
        state['entry_watch'] = [list(k) + [v] for k, v in state['entry_watch'].items()]
