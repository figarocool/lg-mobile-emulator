"""Read-only ordered block trace of the UIM driver after the last ATR byte, until uim_power_down.
Enabled with U310_ATR_TRACE=<atr length>; blocks in the UIM driver regions only."""
import os
from unicorn import UC_HOOK_BLOCK, UC_HOOK_CODE, UC_HOOK_MEM_READ
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R6

RANGES = [(0xa30000, 0xa40000), (0xb68000, 0xb6c800), (0x10e4000, 0x10e7000), (0x12dd000, 0x12de000)]


def attach(uc, state):
    spec = os.environ.get('U310_ATR_TRACE')
    if not spec:
        return
    length = int(spec)
    trace, flags = [], {'reads': 0, 'on': False, 'done': False}
    order = []
    state['atr_order'] = order
    state['atr_trace'] = trace

    def rf(u, access, address, size, value, _):
        flags['reads'] += 1
        flags['last'] = int.from_bytes(u.mem_read(0x84000c94, 4), 'little')
        order.append(['R', hex(flags['last']), hex(u.reg_read(UC_ARM_REG_PC))])
        if flags['reads'] == length:
            flags['on'] = True

    def block(u, address, size, _):
        if flags['on'] and not flags['done']:
            if any(lo <= address < hi for lo, hi in RANGES):
                trace.append(hex(address))
            if address in (0xb6b9ec, 0xb6b9ed):
                flags['done'] = True
                state['stop'] = 'atr trace complete'
                u.emu_stop()

    dumps = []
    state['atr_buffer_dumps'] = dumps

    def callback(u, address, size, _):
        # ATR-complete callback registered by the ISR (0xa3c93e): dump the ISR receive buffer.
        base = int.from_bytes(u.mem_read(0x1d4b9d8, 4), 'little')
        count = int.from_bytes(u.mem_read(base, 2), 'little') if base else None
        dumps.append({'buffer': hex(base), 'count_field': count,
                      'bytes': bytes(u.mem_read(base, 0x40)).hex() if base else None,
                      'rx_ptr': hex(int.from_bytes(u.mem_read(0x1d4b9bc, 4), 'little'))})

    uc.hook_add(UC_HOOK_BLOCK, callback, begin=0xa3c93e, end=0xa3c93e)
    samples = []
    state['atr_isr_samples'] = samples

    def after_byte(u, address, size, _):
        if len(samples) < 80 and flags['reads'] > 0:  # sampled after each ISR byte
            r8 = lambda a: int.from_bytes(u.mem_read(a, 1), 'little')
            r32 = lambda a: int.from_bytes(u.mem_read(a, 4), 'little')
            samples.append({'reads': flags['reads'], 'rf': flags.get('last'), 'state': r8(0x1d4b972), 'tck_flag': r8(0x1d4b96b),
                            'remaining': r32(0x1d4b9c4), 'ptr': hex(r32(0x1d4b9bc)),
                            'count': int.from_bytes(u.mem_read(0x1d4b96a, 2), 'little')})

    uc.hook_add(UC_HOOK_BLOCK, after_byte, begin=0xb6aaa2, end=0xb6aaa2)
    stores = []
    state['atr_stores'] = stores

    def store(u, address, size, _):
        order.append(['S', hex(u.reg_read(UC_ARM_REG_R6)), hex(u.reg_read(UC_ARM_REG_R0))])
        if len(stores) < 200:
            stores.append([hex(u.reg_read(UC_ARM_REG_R0)), hex(u.reg_read(UC_ARM_REG_R6))])

    uc.hook_add(UC_HOOK_CODE, store, begin=0xb6a8ca, end=0xb6a8ca)
    itrace = []
    state['atr_itrace'] = itrace

    def every(u, address, size, _):
        if flags['reads'] >= 1 and len(itrace) < 400 and len([o for o in order if o[0] == 'S']) < 3:
            itrace.append([hex(address), hex(u.reg_read(UC_ARM_REG_R6)), hex(u.reg_read(UC_ARM_REG_R0)),
                           hex(u.reg_read(UC_ARM_REG_R1))])

    uc.hook_add(UC_HOOK_CODE, every)
    uc.hook_add(UC_HOOK_MEM_READ, rf, begin=0x84000c94, end=0x84000c97)
    uc.hook_add(UC_HOOK_BLOCK, block)
