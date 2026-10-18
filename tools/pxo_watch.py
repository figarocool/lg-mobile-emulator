"""Observe original module launches and execution outside the resident CODE.

No instructions, results or scheduler state are modified. RAM execution alone
is not proof that every application function works.
"""
from unicorn import UC_HOOK_CODE, UC_HOOK_BLOCK, UcError
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R4, UC_ARM_REG_LR


def attach(uc, state, *, launch_entry=0x147f964, return_entry=0x147fd08,
           dispatch_entry=0x16675c8, module_probes=None):
    watch = {'launches': [], 'returns': [], 'ram_blocks': 0, 'ram_entries': [], 'modules': {}}
    entries = {}
    probe_entries = set()
    module_probes = module_probes or {}
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
        handle = u.reg_read(UC_ARM_REG_R4)
        watch['returns'].append({'handle': hex(handle)})
        del watch['returns'][:-64]
        register_handle(handle)
    def register_handle(handle):
        if not handle:
            return
        try:
            callback = int.from_bytes(uc.mem_read(handle+0x1c, 4), 'little') & ~1
            raw = bytes(uc.mem_read(handle+0x3c, 64))
            end = next((i for i in range(0, len(raw), 2) if raw[i:i+2] == b'\x00\x00'), len(raw))
            name = raw[:end].decode('utf-16-le')
            if callback:
                entries[callback] = name
                module = watch['modules'].setdefault(name, {'entry': hex(callback), 'executions': 0, 'messages': {}})
                code = int.from_bytes(uc.mem_read(handle+0x10, 4), 'little')
                module.update(handle=hex(handle), code_base=hex(code))
                for label, offset in module_probes.get(name, {}).items():
                    address = code+offset
                    if address in probe_entries:
                        continue
                    probe_entries.add(address)
                    def probe(u, pc, size, _, name=name, label=label):
                        events = watch.setdefault('probes', [])
                        events.append(dict(module=name, label=label, pc=hex(pc),
                            r0=hex(u.reg_read(UC_ARM_REG_R0)), r1=hex(u.reg_read(UC_ARM_REG_R1)),
                            lr=hex(u.reg_read(UC_ARM_REG_LR))))
                        del events[:-128]
                    uc.hook_add(UC_HOOK_CODE, probe, begin=address, end=address)
        except (UcError, UnicodeDecodeError):
            pass
    def dispatch(u, address, size, _):
        register_handle(u.reg_read(UC_ARM_REG_R0))
    def ram(u, address, size, _):
        if address in entries:
            module = watch['modules'][entries[address]]
            module['executions'] += 1
            message = hex(u.reg_read(UC_ARM_REG_R0))
            module['messages'][message] = module['messages'].get(message, 0)+1
            events = module.setdefault('events', [])
            events.append(dict(message=message, r1=hex(u.reg_read(UC_ARM_REG_R1)),
                               r2=hex(u.reg_read(UC_ARM_REG_R2))))
            del events[:-64]
        watch['ram_blocks'] += 1
        entry = hex(address)
        if len(watch['ram_entries']) < 64 and not any(e['pc'] == entry for e in watch['ram_entries']):
            watch['ram_entries'].append({'pc': entry, 'lr': hex(u.reg_read(UC_ARM_REG_LR))})
    uc.hook_add(UC_HOOK_CODE, launch, begin=launch_entry, end=launch_entry)
    uc.hook_add(UC_HOOK_CODE, returned, begin=return_entry, end=return_entry)
    if dispatch_entry is not None:
        uc.hook_add(UC_HOOK_CODE, dispatch, begin=dispatch_entry, end=dispatch_entry)
    uc.hook_add(UC_HOOK_BLOCK, ram, begin=0x01860000, end=0x04ffffff)
    return register_handle
