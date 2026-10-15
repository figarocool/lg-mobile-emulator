"""Read-only breakpoints on U310 UI startup decisions."""
from collections import Counter, deque
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0


def attach(uc, state):
    points = {0x68558: 'UI startup', 0x14441fc: 'service-key combination result',
              0x68622: 'PhoneMngr.pxo presence result',
              0x68646: 'startup diagnostic display', 0x6877c: 'normal startup continuation',
              0x68784: 'additional startup file presence result',
              0x687a2: 'additional startup file metadata result',
              0x687d8: 'startup checks finished',
              0x687f6: 'startup timers initialized',
              0x68812: 'platform initialization finished',
              0x68824: 'first startup service launch'}
    counts = Counter()
    events = deque(maxlen=64)
    state['startup_watch'] = {'counts': counts, 'events': events}

    def observe(u, address, size, _):
        name = points[address]
        counts[name] += 1
        events.append({'point': name, 'pc': hex(address),
                       'r0': hex(u.reg_read(UC_ARM_REG_R0))})

    for address in points:
        uc.hook_add(UC_HOOK_CODE, observe, begin=address, end=address)


def finalize(state):
    if 'startup_watch' in state:
        watch = state['startup_watch']
        watch['counts'] = dict(watch['counts'])
        watch['events'] = list(watch['events'])
