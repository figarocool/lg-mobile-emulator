"""Debugger-call the original PXO launcher in a disposable checkpoint copy."""
import json
from pathlib import Path
from unicorn import UC_HOOK_CODE, UC_HOOK_BLOCK, UcError
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_PC, UC_ARM_REG_LR
from emulator import run, ROOT


def probe(resume, path):
    result = {'path': path, 'events': [], 'dynamic_code': []}
    saved = {}
    def setup(u, state):
        saved['cpu'] = u.context_save()
        tcb = int.from_bytes(u.mem_read(0x19a3f18, 4), 'little')
        task = bytes(u.mem_read(tcb+0x60, 12)).split(b'\x00')[0].decode('ascii')
        result['caller_task'] = task
        if task != 'UI':
            raise ValueError('PXO launcher probe requires the original UI task context')
        def dynamic(u, address, size, _):
            if address != 0x4f01000 and len(result['dynamic_code']) < 64 and hex(address) not in result['dynamic_code']:
                result['dynamic_code'].append(hex(address))
        u.hook_add(UC_HOOK_BLOCK, dynamic, begin=0x01860000, end=0x04ffffff)
        u.mem_write(0x4f00000, path.encode('utf-16-le')+b'\x00\x00')
        for reg, value in [(UC_ARM_REG_R0, 0x4f00000), (UC_ARM_REG_R1, 0),
                           (UC_ARM_REG_R2, 100), (UC_ARM_REG_R3, 0),
                           (UC_ARM_REG_LR, 0x4f01001), (UC_ARM_REG_PC, 0x147f965)]:
            u.reg_write(reg, value)
        def returned(u, address, size, _):
            result['return'] = hex(u.reg_read(UC_ARM_REG_R0))
            state['stop'] = 'original PXO launcher returned'
            u.emu_stop()
        u.hook_add(UC_HOOK_CODE, returned, begin=0x4f01000, end=0x4f01000)
        def observe(u, address, size, _):
            args = [u.reg_read(r) for r in [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]]
            event = {'pc': hex(address), 'args': [hex(v) for v in args]}
            if address == 0x898df2:
                try:
                    event['format'] = bytes(u.mem_read(args[0], 256)).split(b'\x00')[0].decode('ascii')
                    event['message'] = bytes(u.mem_read(args[3], 256)).split(b'\x00')[0].decode('ascii')
                except (UcError, UnicodeDecodeError):
                    pass
            result['events'].append(event)
            del result['events'][:-128]
        for a in [0x147f9f0, 0x147fa0e, 0x147fd08, 0x896dba, 0x898df2]:
            u.hook_add(UC_HOOK_CODE, observe, begin=a, end=a)
    def finish(u, state):
        if 'return' not in result:
            result['failure'] = state['stop']
        u.context_restore(saved['cpu'])
    s = run('amss', True, 10000000, True, lcd=True, banks=True, irq=True,
            mmc=True, block_trace=True, mdsp_management=True, keypad=True,
            resume=resume, debug_setup=setup, debug_finish=finish)
    result['api_watch'] = s['native_api_watch']
    result['fatal_entry'] = s.get('fatal_entry')
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path, default=ROOT/'analysis/amss_resources_next6.zip')
    parser.add_argument('--path', default='LGAPP/Pxo/PhoneMngr.pxo')
    args = parser.parse_args()
    report = probe(args.resume, args.path)
    (ROOT/'analysis/native_pxo_launch.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'api_watch'}, indent=2))
