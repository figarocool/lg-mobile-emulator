"""One run: (1) inject UIM command 0x114 (card reset), (2) after a delay call the original
mmgsdi_card_pup API, then let the guest run with the inferred UIM UART + minimal USIM.

Diagnostic bring-up of the SIM path; not how the phone starts the card. From tools/:
U310_MSG_WATCH=8000 python3 probe_sim_bringup.py [--delay N] [--limit N]
"""
import argparse
import json
from pathlib import Path
from unicorn import UC_HOOK_BLOCK, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_PC, UC_ARM_REG_LR, UC_ARM_REG_SP)
from emulator import run, ROOT

Q_GET, Q_PUT, SET_SIGS = 0x7c0720, 0x7c0758, 0x8a04fc
FREE_Q, CMD_Q, UIM_TCB = 0x1d4a688, 0x1d4a67c, 0x1c03c54
CARD_PUP = 0x88dd80
RETURN, CALLBACK = 0x04f01000, 0x04f01100


def bringup(resume, delay, limit, out, client=(0, 0), skip_reset=False):
    result = {'stages': []}
    saved = {}
    plan = [] if skip_reset else ['get', 'put', 'sigs']
    stage = {'name': 'wait_reset' if not skip_reset else 'wait_pup', 'start': None}

    def task_context(u):
        cpsr = u.reg_read(UC_ARM_REG_CPSR)
        # REX treats system (0x1f) and IRQ (0x12) as interrupt context; tasks run in supervisor mode.
        return cpsr & 0x1f == 0x13

    def call(u, function, args, stack=(), thumb=False):
        sp = (saved['sp'] - 0x100) & ~7
        u.mem_write(sp, b''.join(v.to_bytes(4, 'little') for v in stack) or b'\0' * 8)
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            u.reg_write(reg, value)
        u.reg_write(UC_ARM_REG_SP, sp)
        u.reg_write(UC_ARM_REG_LR, RETURN | 1)
        u.reg_write(UC_ARM_REG_PC, function | int(thumb))

    def setup(u, state):
        def block(u, address, size, _):
            result['blocks_seen'] = result.get('blocks_seen', 0) + 1
            if task_context(u):
                result['task_context_blocks'] = result.get('task_context_blocks', 0) + 1
            if stage['name'] in ('wait_reset', 'wait_pup') and task_context(u):
                result['wait_info'] = [stage['start'], state['instructions']]
                if stage['name'] == 'wait_pup' and state['instructions'] < stage['start'] + delay:
                    return
                saved['cpu'] = u.context_save()
                saved['sp'] = u.reg_read(UC_ARM_REG_SP)
                if stage['name'] == 'wait_reset':
                    stage['name'] = 'reset'
                    call(u, Q_GET, (FREE_Q,))
                else:
                    stage['name'] = 'pup'
                    u.mem_write(CALLBACK, b'\x70\x47')
                    call(u, CARD_PUP, (client[0], client[1], 0, CALLBACK | 1), (0, 1), thumb=True)
                result['stages'].append([stage['name'], state['instructions']])
                state['stop'] = 'debugger: call started'
                u.emu_stop()
        u.hook_add(UC_HOOK_BLOCK, block)

        def returned(u, address, size, _):
            state['stop'] = 'debugger: call returned'
            u.emu_stop()
        u.hook_add(UC_HOOK_CODE, returned, begin=RETURN, end=RETURN)

        def callback(u, address, size, _):
            result.setdefault('callbacks', []).append([hex(u.reg_read(r)) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1)])
        u.hook_add(UC_HOOK_CODE, callback, begin=CALLBACK, end=CALLBACK)

    def finish(u, state):
        if state['stop'] == 'debugger: call started':
            return True
        if state['stop'] != 'debugger: call returned':
            return False
        value = u.reg_read(UC_ARM_REG_R0)
        if stage['name'] == 'reset':
            step = plan.pop(0)
            result['stages'].append([step, hex(value)])
            if step == 'get':
                u.mem_write(value + 0x10, (0x114).to_bytes(2, 'little'))
                call(u, Q_PUT, (CMD_Q, value))
            elif step == 'put':
                call(u, SET_SIGS, (UIM_TCB, 2))
            else:
                u.context_restore(saved['cpu'])
                stage['name'], stage['start'] = 'wait_pup', state['instructions']
        else:
            result['pup_return'] = hex(value)
            u.context_restore(saved['cpu'])
            stage['name'] = 'done'
        return True

    s = run('amss', True, limit, True, lcd=True, banks=True, irq=True, mmc=True, block_trace=True,
            mdsp_management=True, keypad=True, uim_card=True, resume=resume, debug_setup=setup,
            debug_finish=finish, save_checkpoint=ROOT / 'analysis/sim_bringup_state.zip')
    result.update(stop=s['stop'], fatal_entry=s.get('fatal_entry'), uim_uart=s.get('uim_uart'),
                  msg_watch=s.get('msg_watch'), stage=stage['name'], pc=s.get('pc'), registers=s.get('registers'),
                  timer=s.get('timer_irq'))
    out.write_text(json.dumps(result, indent=1) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path, default=ROOT / 'analysis/cold300.zip')
    parser.add_argument('--delay', type=int, default=4000000)
    parser.add_argument('--limit', type=int, default=40000000)
    parser.add_argument('--skip-reset', action='store_true')
    args = parser.parse_args()
    r = bringup(args.resume, args.delay, args.limit, ROOT / 'analysis/sim_bringup.json', skip_reset=args.skip_reset)
    print(r['stages'], r.get('pup_return'), r.get('callbacks'), r['stage'], r['stop'])
