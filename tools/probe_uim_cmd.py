"""Debugger-inject one command into the UIM driver queue using the original q_get/q_put/rex_set_sigs.

This is a diagnostic to discover which hardware the UIM driver touches; it is not how the
phone starts the card. Command ids and the buffer layout are inferred from the UIM loop
(command id is the halfword at +0x10; free queue 0x1d4a688, command queue 0x1d4a67c).
Usage: U310_MMIO_CENSUS=1 python3 tools/probe_uim_cmd.py [--cmd 0x11a] [--limit N]
"""
import argparse
import json
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_PC, UC_ARM_REG_LR, UC_ARM_REG_SP
from emulator import run, ROOT

Q_GET, Q_PUT, SET_SIGS = 0x7c0720, 0x7c0758, 0x8a04fc
FREE_Q, CMD_Q, UIM_TCB = 0x1d4a688, 0x1d4a67c, 0x1c03c54
RETURN = 0x04f01000
UIM_STATE = 0x17f3a58


def probe(resume, command, limit, out):
    result = {'command': hex(command), 'steps': []}
    plan = []
    saved = {}

    def call(u, function, r0, r1=0):
        u.reg_write(UC_ARM_REG_R0, r0)
        u.reg_write(UC_ARM_REG_R1, r1)
        u.reg_write(UC_ARM_REG_LR, RETURN | 1)
        u.reg_write(UC_ARM_REG_PC, function)
        u.reg_write(UC_ARM_REG_SP, (saved['sp'] - 0x100) & ~7)

    def setup(u, state):
        saved['cpu'] = u.context_save()
        saved['sp'] = u.reg_read(UC_ARM_REG_SP)
        result['state_before'] = int.from_bytes(u.mem_read(UIM_STATE, 1), 'little')
        plan.extend(['get', 'put', 'sigs', 'done'])

        def returned(u, address, size, _):
            state['stop'] = 'debugger: injected call returned'
            u.emu_stop()
        u.hook_add(UC_HOOK_CODE, returned, begin=RETURN, end=RETURN)
        call(u, Q_GET, FREE_Q)

    def finish(u, state):
        if state['stop'] != 'debugger: injected call returned':
            return False
        step = plan.pop(0)
        value = u.reg_read(UC_ARM_REG_R0)
        result['steps'].append({'step': step, 'r0': hex(value)})
        if step == 'get':
            if not value:
                raise ValueError('UIM free queue is empty')
            saved['buffer'] = value
            u.mem_write(value + 0x10, command.to_bytes(2, 'little'))
            call(u, Q_PUT, CMD_Q, value)
        elif step == 'put':
            call(u, SET_SIGS, UIM_TCB, 2)
        else:
            u.context_restore(saved['cpu'])
            state['stop'] = 'injection complete'
        return True

    s = run('amss', True, limit, True, lcd=True, banks=True, irq=True, mmc=True, block_trace=True,
            mdsp_management=True, keypad=True, uim_card=True, resume=resume, debug_setup=setup, debug_finish=finish,
            save_checkpoint=ROOT / 'analysis/uim_probe_state.zip')
    result['stop'] = s['stop']
    result['mmio_census'] = s.get('mmio_census')
    result['uim_watch'] = s.get('uim_watch')
    result['uim_uart'] = s.get('uim_uart')
    result['msg_watch'] = s.get('msg_watch')
    result['uim_blocks'] = (s.get('task_coverage') or {}).get('UIM')
    out.write_text(json.dumps(result, indent=1) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path, default=ROOT / 'analysis/cold300.zip')
    parser.add_argument('--cmd', type=lambda v: int(v, 0), default=0x11a)
    parser.add_argument('--limit', type=int, default=40000000)
    args = parser.parse_args()
    r = probe(args.resume, args.cmd, args.limit, ROOT / 'analysis/uim_cmd_probe.json')
    print(r['steps'], r['stop'])
