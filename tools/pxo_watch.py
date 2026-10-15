"""Observe original module launches and execution outside the resident CODE.

No instructions, results or scheduler state are modified. RAM execution alone
is not proof that every application function works.
"""
from unicorn import UC_HOOK_CODE, UC_HOOK_BLOCK, UcError
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R4, UC_ARM_REG_LR


def attach(uc, state):
    watch = {'launches': [], 'returns': [], 'ram_blocks': 0, 'ram_entries': [], 'modules': {}}
    entries = {}
    state['pxo_watch'] = watch
    def launch(u, address, size, _):
        pointer = u.reg_read(UC_ARM_REG_R0)
        name = None
        try:
            raw = bytes(u.mem_read(pointer, 512))
            end = next((i for i in range(0, len(raw), 2) if raw[i:i+2] == b'\x00\x00'), len(raw))
            name = raw[:end].decode('utf-16-le')
        except (UcError, UnicodeDecodeError):
            pass
        watch['launches'].append({'path': name, 'caller': hex(u.reg_read(UC_ARM_REG_LR))})
        del watch['launches'][:-64]
    def returned(u, address, size, _):
        watch['returns'].append({'handle': hex(u.reg_read(UC_ARM_REG_R4))})
        del watch['returns'][:-64]
    def dispatch(u, address, size, _):
        handle = u.reg_read(UC_ARM_REG_R0)
        if not handle:
            return
        try:
            callback = int.from_bytes(u.mem_read(handle+0x1c, 4), 'little') & ~1
            raw = bytes(u.mem_read(handle+0x3c, 64))
            end = next((i for i in range(0, len(raw), 2) if raw[i:i+2] == b'\x00\x00'), len(raw))
            name = raw[:end].decode('utf-16-le')
            if callback:
                entries[callback] = name
                watch['modules'].setdefault(name, {'entry': hex(callback), 'executions': 0, 'messages': {}})
        except (UcError, UnicodeDecodeError):
            pass
    def ram(u, address, size, _):
        if address in entries:
            module = watch['modules'][entries[address]]
            module['executions'] += 1
            message = hex(u.reg_read(UC_ARM_REG_R0))
            module['messages'][message] = module['messages'].get(message, 0)+1
        watch['ram_blocks'] += 1
        entry = hex(address)
        if len(watch['ram_entries']) < 64 and not any(e['pc'] == entry for e in watch['ram_entries']):
            watch['ram_entries'].append({'pc': entry, 'lr': hex(u.reg_read(UC_ARM_REG_LR))})
    uc.hook_add(UC_HOOK_CODE, launch, begin=0x147f964, end=0x147f964)
    uc.hook_add(UC_HOOK_CODE, returned, begin=0x147fd08, end=0x147fd08)
    uc.hook_add(UC_HOOK_CODE, dispatch, begin=0x16675c8, end=0x16675c8)
    uc.hook_add(UC_HOOK_BLOCK, ram, begin=0x01860000, end=0x04ffffff)
