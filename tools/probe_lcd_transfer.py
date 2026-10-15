"""Debugger-call the original diagnostic bitmap renderer; capture real LCD transfers.

Runs only a copy of a checkpoint. Firmware code and returned values are intact.
No checkpoint is saved and production NAND images are not modified.
"""
import json
from pathlib import Path
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_PC, UC_ARM_REG_LR
from emulator import run, ROOT


def probe(resume, bitmap=None):
    context = {}
    transfers = []
    def setup(u, state):
        context['cpu'] = u.context_save()
        # One distinct RGB565 value per row, with four-pixel aligned stride.
        u.mem_write(0x4f00000, b''.join((row+1).to_bytes(2, 'little')*136
                                       for row in range(37)))
        sp = u.reg_read(UC_ARM_REG_SP)-16
        u.reg_write(UC_ARM_REG_SP, sp)
        u.mem_write(sp, (213).to_bytes(4, 'little'))
        for reg, value in [(UC_ARM_REG_R0, bitmap if bitmap is not None else 0x4f00000), (UC_ARM_REG_R1, 20),
                           (UC_ARM_REG_R2, 177), (UC_ARM_REG_R3, 154),
                           (UC_ARM_REG_LR, 0x4f01001), (UC_ARM_REG_PC, 0x10df6e1)]:
            u.reg_write(reg, value)
        def capture(u, access, address, size, value, _):
            transfers.append({'port': hex(address), 'size': size, 'value': value,
                              'pc': hex(u.reg_read(UC_ARM_REG_PC))})
        for a in [0x20000000, 0x20100000]:
            u.hook_add(UC_HOOK_MEM_WRITE, capture, begin=a, end=a+3)
        def returned(u, address, size, _):
            state['stop'] = 'original LCD renderer returned'
            u.emu_stop()
        u.hook_add(UC_HOOK_CODE, returned, begin=0x4f01000, end=0x4f01000)
    def finish(u, state):
        if state['stop'] != 'original LCD renderer returned':
            raise ValueError(f'Renderer failed: {state["stop"]}, PC={u.reg_read(UC_ARM_REG_PC):x}')
        u.context_restore(context['cpu'])
    state = run('amss', True, 2000000, True, lcd=True, banks=True, irq=True,
                mmc=True, block_trace=True, mdsp_management=True, keypad=True,
                resume=resume, debug_setup=setup, debug_finish=finish)
    return {'stop': state['stop'], 'transfers': transfers}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bitmap', type=lambda value: int(value, 0), help='Original guest bitmap address instead of row-pattern probe')
    parser.add_argument('--resume', type=Path, default=ROOT/'analysis/amss_resources_reboot.zip')
    args = parser.parse_args()
    report = probe(args.resume, args.bitmap)
    (ROOT/'analysis/native_lcd_transfer.json').write_text(json.dumps(report, indent=2)+'\n')
    from lcd_bus import LcdBus
    from unicorn import UC_MEM_WRITE
    panel = LcdBus()
    for transfer in report['transfers']:
        panel.access(None, UC_MEM_WRITE, int(transfer['port'], 16),
                     transfer['size'], transfer['value'], None)
    if report['transfers']:
        panel.export(ROOT/'analysis/native_diagnostic_display.ppm')
    print(report['stop'], len(report['transfers']), 'transfers')
    print(report['transfers'][:10])
