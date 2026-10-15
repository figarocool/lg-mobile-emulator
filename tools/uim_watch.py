"""Read-only log of accesses to the inferred UIM UART window (0x84000c80..0x84000cff)."""
from collections import deque
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_READ
from unicorn.arm_const import UC_ARM_REG_PC

BEGIN, END = 0x84000c80, 0x84000cff


def attach(uc, state):
    events = deque(maxlen=4000)
    state['uim_watch'] = events

    def observe(u, access, address, size, value, _):
        if address == 0x84000248:
            return  # timer acknowledge, thousands per second
        item = ['r' if access == UC_MEM_READ else 'w', hex(address), hex(value) if access != UC_MEM_READ else
                hex(int.from_bytes(u.mem_read(address, 4), 'little')), hex(u.reg_read(UC_ARM_REG_PC)), 1]
        if events and events[-1][:4] == item[:4]:
            events[-1][4] += 1  # run-length encode busy-wait polling
        else:
            events.append(item)

    uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, observe, begin=BEGIN, end=END)
    # Interrupt controller registers (mask/enable writes show which source the UIM driver arms).
    uc.hook_add(UC_HOOK_MEM_WRITE, observe, begin=0x84000240, end=0x840002c3)


def finalize(state):
    if 'uim_watch' in state:
        state['uim_watch'] = list(state['uim_watch'])
