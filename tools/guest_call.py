"""Call a guest function synchronously from Python (outside emu_start), then restore the CPU exactly as it was.

The stub address holds a NOP; execution is stopped when it is reached. Memory writes made by the function stay
(that is the point: allocate a buffer, queue a message), registers and CPSR are restored.
"""
from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP)

STUB = 0x04f01000
ARG_REGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)


class GuestCallError(RuntimeError):
    pass


def call(uc, function, args=(), limit=2_000_000, thumb=True):
    """Run function(*args) (up to 4 register arguments) and return r0."""
    saved = uc.context_save()
    sp = uc.reg_read(UC_ARM_REG_SP) - 64          # scratch below the interrupted stack
    try:
        uc.mem_write(STUB, b'\x00\xbf\x00\xbf')
        for reg, value in zip(ARG_REGS, args):
            uc.reg_write(reg, value & 0xffffffff)
        uc.reg_write(UC_ARM_REG_SP, sp & ~7)
        uc.reg_write(UC_ARM_REG_LR, STUB | 1)
        uc.reg_write(UC_ARM_REG_CPSR, 0x13 | (0x20 if thumb else 0))   # supervisor, interrupts enabled
        start = function | 1 if thumb else function
        uc.emu_start(start, STUB, count=limit)
        if uc.reg_read(UC_ARM_REG_PC) & ~1 != STUB:
            raise GuestCallError(f'function 0x{function:x} did not return within {limit} instructions (pc=0x{uc.reg_read(UC_ARM_REG_PC):x} lr=0x{uc.reg_read(UC_ARM_REG_LR):x})')
        return uc.reg_read(UC_ARM_REG_R0)
    finally:
        uc.context_restore(saved)
