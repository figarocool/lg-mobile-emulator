"""Read-only trace of original FS/NV requests, excluding file/NV payloads."""
from unicorn import UC_HOOK_CODE, UcError
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_LR


def attach(uc, state):
    points = {0x161ebcc: 'open/create', 0x161ec2e: 'close',
              0x161ec6c: 'read', 0x161ecb6: 'write',
              0x161f21c: 'mkdir', 0x161f2a4: 'presence', 0x10d219a: 'nv'}
    watch = {'counts': {}, 'paths': {}, 'recent': []}
    state['native_api_watch'] = watch

    def observe(u, address, size, _):
        op = points[address]
        watch['counts'][op] = watch['counts'].get(op, 0)+1
        r0 = u.reg_read(UC_ARM_REG_R0)
        event = {'operation': op, 'caller': hex(u.reg_read(UC_ARM_REG_LR))}
        try:
            if op in ('open/create', 'mkdir', 'presence'):
                raw = bytes(u.mem_read(r0, 256)).split(b'\x00', 1)[0]
                event['path'] = raw.decode('ascii')
                watch['paths'][event['path']] = watch['paths'].get(event['path'], 0)+1
                event['mode'] = u.reg_read(UC_ARM_REG_R1)
            elif op == 'nv':
                raw = bytes(u.mem_read(r0+4, 4))
                event.update(item=int.from_bytes(raw[:2], 'little'), command=int.from_bytes(raw[2:], 'little'))
            else:
                event['handle'] = r0
                if op != 'close':
                    event['length'] = u.reg_read(UC_ARM_REG_R2)
        except (UcError, UnicodeDecodeError):
            event['arguments_available'] = False
        watch['recent'].append(event)
        del watch['recent'][:-64]

    for address in points:
        uc.hook_add(UC_HOOK_CODE, observe, begin=address, end=address)
