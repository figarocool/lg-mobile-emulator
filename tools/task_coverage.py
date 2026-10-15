"""Read-only coverage of basic blocks executed while chosen REX tasks are current (U310_COVERAGE=UIM,GSDI)."""
import os
from collections import Counter, defaultdict
from unicorn import UC_HOOK_BLOCK

CURRENT_TCB = 0x019a3f18
TCBS = {'UIM': 0x1c03c54, 'GSDI': 0x1c0b40c, 'GSTK': 0x1c0b5e8, 'UI': 0x1bf7628, 'PS': 0x1bf91bc,
        'MAIN': 0x1c0a230, 'CM': 0x1be9eb8, 'MMOC': 0x1c09454}


def attach(uc, state):
    spec = os.environ.get('U310_COVERAGE')
    if not spec:
        return
    wanted = {TCBS[name]: name for name in spec.split(',')}
    cover = defaultdict(Counter)
    state['task_coverage'] = cover

    def block(u, address, size, _):
        tcb = int.from_bytes(u.mem_read(CURRENT_TCB, 4), 'little')
        if tcb in wanted:
            cover[wanted[tcb]][address] += 1

    uc.hook_add(UC_HOOK_BLOCK, block)


def finalize(state):
    if 'task_coverage' in state:
        state['task_coverage'] = {name: {hex(a): n for a, n in sorted(c.items())}
                                  for name, c in state['task_coverage'].items()}
