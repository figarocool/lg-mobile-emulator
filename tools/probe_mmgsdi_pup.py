"""Debugger-call the original MMGSDI library API mmgsdi_card_pup (0x88dd80), then let the guest run.

Diagnostic only: it asks the original firmware path (MMGSDI task -> UIM command 0x11c -> uimdrv)
to power the card, to discover which hardware registers the UIM driver touches. Signature
inferred from the code: r0,r1 = client id, r2 = stored in the request, r3 = response callback
(must be non-zero), stack[0] = option (0 or 1), stack[1] = client reference.
Usage (from tools/): U310_MMIO_CENSUS=1 python3 probe_mmgsdi_pup.py [--client LO HI] [--option N]
"""
import argparse
import json
from pathlib import Path
from unicorn import UC_HOOK_CODE, UC_HOOK_BLOCK
from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_PC, UC_ARM_REG_LR, UC_ARM_REG_SP)
from emulator import run, ROOT

CARD_PUP = 0x88dd80
RETURN = 0x04f01000
CALLBACK = 0x04f01100


def probe(resume, client, option, limit, out):
    result = {'client': [hex(v) for v in client], 'option': option, 'callbacks': []}
    saved = {}

    def setup(u, state):
        armed = {'done': False}

        def at_sleep_loop(u, address, size, _):
            """Inject from the SLEEP task (normal task context, not an interrupt)."""
            cpsr = u.reg_read(UC_ARM_REG_CPSR)
            # REX treats system (0x1f) and IRQ (0x12) as interrupt context; tasks run in supervisor mode.
            if armed['done'] or cpsr & 0x1f != 0x13 or cpsr & 0x80:
                return
            armed['done'] = True
            result['injected_at_instruction'] = state['instructions']
            saved['cpu'] = u.context_save()
            sp = (u.reg_read(UC_ARM_REG_SP) - 0x100) & ~7
            u.mem_write(sp, option.to_bytes(4, 'little') + (1).to_bytes(4, 'little'))
            u.mem_write(CALLBACK, b'\x70\x47')  # bx lr
            for reg, value in [(UC_ARM_REG_R0, client[0]), (UC_ARM_REG_R1, client[1]), (UC_ARM_REG_R2, 0),
                               (UC_ARM_REG_R3, CALLBACK | 1), (UC_ARM_REG_SP, sp),
                               (UC_ARM_REG_LR, RETURN | 1), (UC_ARM_REG_PC, CARD_PUP | 1)]:
                u.reg_write(reg, value)
            state['stop'] = 'debugger: injection started'
            u.emu_stop()
        u.hook_add(UC_HOOK_BLOCK, at_sleep_loop)

        def returned(u, address, size, _):
            result['return'] = hex(u.reg_read(UC_ARM_REG_R0))
            state['stop'] = 'debugger: card_pup returned'
            u.emu_stop()
        u.hook_add(UC_HOOK_CODE, returned, begin=RETURN, end=RETURN)

        def callback(u, address, size, _):
            result['callbacks'].append([hex(u.reg_read(UC_ARM_REG_R0)), hex(u.reg_read(UC_ARM_REG_R1)),
                                        hex(u.reg_read(UC_ARM_REG_R2))])
        u.hook_add(UC_HOOK_CODE, callback, begin=CALLBACK, end=CALLBACK)

    def finish(u, state):
        if state['stop'] == 'debugger: injection started':
            return True
        if state['stop'] == 'debugger: card_pup returned':
            u.context_restore(saved['cpu'])
            state['stop'] = 'injection complete'
            return True
        result['lr'] = hex(u.reg_read(UC_ARM_REG_LR))
        result['cpsr'] = hex(u.reg_read(UC_ARM_REG_CPSR))
        return False

    s = run('amss', True, limit, True, lcd=True, banks=True, irq=True, mmc=True, block_trace=True,
            mdsp_management=True, keypad=True, uim_card=True, resume=resume, debug_setup=setup, debug_finish=finish,
            save_checkpoint=ROOT / 'analysis/mmgsdi_pup_state.zip')
    result['stop'] = s['stop']
    result['fatal_entry'] = s.get('fatal_entry')
    import collections
    result['signals'] = {' '.join(k): v for k, v in collections.Counter(tuple(e) for e in s.get('rex_signal_watch', [])).items()}
    result['registers'] = s.get('registers')
    result['pc'] = s.get('pc')
    result['uim_uart'] = s.get('uim_uart')
    result['msg_watch'] = s.get('msg_watch')
    result['mmio_census'] = s.get('mmio_census')
    out.write_text(json.dumps(result, indent=1) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path, default=ROOT / 'analysis/cold300.zip')
    parser.add_argument('--client', type=lambda v: int(v, 0), nargs=2, default=[0, 0])
    parser.add_argument('--option', type=int, default=0)
    parser.add_argument('--limit', type=int, default=30000000)
    args = parser.parse_args()
    r = probe(args.resume, args.client, args.option, args.limit, ROOT / 'analysis/mmgsdi_pup_probe.json')
    print(r['return'] if 'return' in r else 'no return', r['callbacks'], r['stop'])
