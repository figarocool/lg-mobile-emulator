"""Read-only log of reads from the GPIO input words, with caller addresses."""
from collections import Counter
from unicorn import UC_HOOK_MEM_READ
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC

WATCHED = {0x48000060: 'GPIO in 60', 0x48000070: 'GPIO in 70'}


def attach(uc, state):
    seen = Counter()
    state['gpio_watch'] = seen

    def read(u, access, address, size, value, _):
        value = int.from_bytes(u.mem_read(address, 4), 'little')
        seen[(hex(address), hex(u.reg_read(UC_ARM_REG_PC)), hex(u.reg_read(UC_ARM_REG_LR)), hex(value))] += 1

    for address in WATCHED:
        uc.hook_add(UC_HOOK_MEM_READ, read, begin=address, end=address + 3)


def finalize(state):
    if 'gpio_watch' in state:
        state['gpio_watch'] = [list(k) + [v] for k, v in state['gpio_watch'].items()]
