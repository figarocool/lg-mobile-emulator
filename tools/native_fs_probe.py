"""Isolated debugger call to original asynchronous filesystem API.

Starts from a copy of a checkpoint, without modifying its ZIP or CODE.
File operations affect only the simulated NAND copy. API return values and
filesystem algorithms are executed by the original guest, without replacement.
"""
import argparse
import json
import hashlib
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR
from emulator import run, ROOT


def probe(resume, path, limit=1000000, operation='test', save=None, handle=None, payload=None, length=0):
    result = {}
    original = {}
    def setup(uc, state):
        name, response, stop = 0x04f00000, 0x04f00100, 0x04f01000
        raw = path.encode('ascii') + b'\x00'
        if len(raw) > 256:
            raise ValueError('Path too long for probe')
        uc.mem_write(name, raw)
        uc.mem_write(response, b'\xcc'*32)
        original['context'] = uc.context_save()
        original['tcb'] = bytes(uc.mem_read(0x19a3f18, 4))
        def finished(u, address, size, _):
            result['response'] = bytes(u.mem_read(response, 32)).hex()
            state['stop'] = 'debugger: original filesystem request API returned'
            u.emu_stop()
        uc.hook_add(UC_HOOK_CODE, finished, begin=stop, end=stop)
        uc.reg_write(UC_ARM_REG_R0, name)
        uc.reg_write(UC_ARM_REG_R1, 1)  # Same mode as the original UI open.
        uc.reg_write(UC_ARM_REG_R2, 0)  # No callback.
        uc.reg_write(UC_ARM_REG_R3, response)
        uc.reg_write(UC_ARM_REG_LR, stop | 1)
        uc.reg_write(UC_ARM_REG_CPSR, uc.reg_read(UC_ARM_REG_CPSR) | 32)
        if operation in ('create', 'open', 'write', 'read'):
            from unicorn.arm_const import UC_ARM_REG_SP
            parameters = 0x04f00200
            uc.mem_write(parameters, b'\x00'*16)
            sp = uc.reg_read(UC_ARM_REG_SP)-16
            uc.reg_write(UC_ARM_REG_SP, sp)
            uc.mem_write(sp, response.to_bytes(4, 'little'))
            uc.reg_write(UC_ARM_REG_R1, 0 if operation == 'create' else 2)
            uc.reg_write(UC_ARM_REG_R2, parameters)
            uc.reg_write(UC_ARM_REG_R3, 0)
            uc.reg_write(UC_ARM_REG_PC, 0x0161ebcd)
            if operation in ('write', 'read'):
                buffer = 0x04000000
                data = payload if operation == 'write' else b'\xcc'*length
                if data is None or len(data) > 0x00d00000:
                    raise ValueError('Invalid data size')
                uc.mem_write(buffer, data)
                uc.reg_write(UC_ARM_REG_R0, handle)
                uc.reg_write(UC_ARM_REG_R1, buffer)
                uc.reg_write(UC_ARM_REG_R2, len(data))
                uc.reg_write(UC_ARM_REG_PC, 0x0161ecb7 if operation == 'write' else 0x0161ec6d)
                original['buffer'] = (buffer, len(data))
        elif operation == 'close':
            uc.reg_write(UC_ARM_REG_R0, handle)
            uc.reg_write(UC_ARM_REG_R1, 0)
            uc.reg_write(UC_ARM_REG_R2, response)
            uc.reg_write(UC_ARM_REG_PC, 0x0161ec2f)
        else:
            uc.reg_write(UC_ARM_REG_PC, 0x0161f2a5)
    def finish(uc, state):
        if 'response' not in result:
            from unicorn.arm_const import UC_ARM_REG_PC
            raise ValueError(f'Native API did not return: {state["stop"]}, PC={uc.reg_read(UC_ARM_REG_PC):x}; refusing to save altered CPU state')
        if bytes(uc.mem_read(0x19a3f18, 4)) != original['tcb']:
            raise ValueError('Native API returned in a different task')
        uc.context_restore(original['context'])
        if 'buffer' in original:
            address, size = original['buffer']
            data = bytes(uc.mem_read(address, size))
            result['buffer_length'] = size
            result['buffer_sha256'] = hashlib.sha256(data).hexdigest()
    state = run('amss', True, limit, True, lcd=True, banks=True, irq=True,
                mmc=True, block_trace=True, mdsp_management=True, keypad=True,
                resume=resume, debug_setup=setup, debug_finish=finish, save_checkpoint=save)
    result.update(path=path if operation in ('test', 'open', 'create') else None,
                  handle=handle, operation=operation, stop=state['stop'], pc=state['pc'],
                  instructions=state['instructions'], trace=state['trace'],
                  fatal_entry=state.get('fatal_entry'),
                  note='Debugger call to original filesystem API, with CPU restored after return. Response layout under investigation.')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path, default=ROOT/'analysis/amss_fs_compat.zip')
    parser.add_argument('--path', default='LGAPP/Pxo/PhoneMngr.pxo')
    parser.add_argument('--operation', choices=['test', 'create', 'open', 'write', 'read', 'close'], default='test')
    parser.add_argument('--save-checkpoint', type=Path)
    parser.add_argument('--handle', type=lambda value: int(value, 0))
    parser.add_argument('--data', type=Path)
    parser.add_argument('--length', type=int, default=0)
    parser.add_argument('--limit', type=int, default=10000000)
    args = parser.parse_args()
    if args.operation in ('read', 'write', 'close') and args.handle is None:
        parser.error('read, write and close require --handle')
    if args.operation == 'write' and args.data is None:
        parser.error('write requires --data')
    result = probe(args.resume, args.path, limit=args.limit, operation=args.operation, save=args.save_checkpoint,
                   handle=args.handle, payload=args.data.read_bytes() if args.data else None, length=args.length)
    output = ROOT/'analysis/native_fs_probe.json'
    output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'trace'}, indent=2))
