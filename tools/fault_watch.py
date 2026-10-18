"""Debugger breakpoint on the fatal/assert entry recovered from U310 callers."""
from unicorn import UC_HOOK_CODE, UcError
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3

ENTRY = 0x0161e028

def attach(uc, state, entry=ENTRY):
    def string(address):
        data = bytearray()
        for offset in range(256):
            try:
                byte = bytes(uc.mem_read(address+offset, 1))[0]
            except UcError:
                return None
            if byte == 0:
                return data.decode('ascii') if data and all(32 <= b < 127 for b in data) else None
            data.append(byte)
        return None

    def hook(u, address, size, _):
        args = [u.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
        state['fatal_entry'] = {'pc': hex(address), 'arguments': [hex(v) for v in args],
                                'line_candidate': args[0], 'file_candidate': string(args[1]),
                                'message_candidate': string(args[2])}
        state['stop'] = 'debugger breakpoint at firmware fatal/assert entry'
        u.emu_stop()
    uc.hook_add(UC_HOOK_CODE, hook, begin=entry, end=entry)
