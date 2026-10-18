#!/usr/bin/env python3
"""Experimental U880 ARM926 core, shared by emulator and reset probes.

Strict mode stops on unknown peripherals and uninitialized RAM. Explicit
shadow-MMIO and zero-RAM options enable diagnostic approximations. Shared
NAND/MMC models and a separate U880 LCD model are optional. Captured runtime
RAM is never treated as a cold-boot checkpoint; firmware is not patched.
"""
from collections import deque
import hashlib
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

from unicorn import (Uc, UcError, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE,
                     UC_HOOK_MEM_INVALID, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE,
                     UC_MEM_WRITE_UNMAPPED, UC_MEM_READ_UNMAPPED, UC_HOOK_BLOCK)
from unicorn.arm_const import (UC_CPU_ARM_926, UC_ARM_REG_CPSR, UC_ARM_REG_PC,
                               UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR,
                               UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7)
from decrypt_u880_code import LOAD


def run(amss, limit, shadow=False, zero_ram=False, block_trace=False, banks=False,
        nand=False, nand_image=None, lcd=False, live_dir=None, mmc=False, fatal_entries=(),
        synthetic_ssikyu=False, page_crypto=None, keypad=False, keys_file=None, press=(),
        manager_open_return=None, irq=False, debug_at=None, debug_session=None,
        debug_continue=False, synthetic_country=None, watch_entries=(),
        post_import_limit=None, dynamic_code=False, fast_import=False,
        resume=None, save_checkpoint=None, fast=False, cstring_entries=(),
        pxo_watch_profile=None, pxo_handles=(), debug_on_resume=False, flip=None, stop_requested=None, uim_card=False):
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    uc.ctl_set_cpu_model(UC_CPU_ARM_926)
    end = LOAD+len(amss)
    if zero_ram:
        uc.mem_map(0, 0x5000000)
        uc.mem_map(0xffff2000, 0x1000)
    else:
        uc.mem_map(LOAD, (len(amss)+4095)&~4095)
    uc.mem_write(LOAD, amss)
    pages = set(range(LOAD, (end+4095)&~4095, 4096))
    if zero_ram:
        pages.update(range(0, 0x5000000, 4096))
        pages.add(0xffff2000)
    initialized = set()
    shadow_pages = set()
    register_banks = None
    controller = None
    panel = None
    mmc_device = None
    keypad_device = None
    flip_sensor = None
    if flip is not None:
        if not shadow:
            raise ValueError('Flip input requires shadow-MMIO')
        from gpio_inputs import FlipSensor
        flip_sensor = FlipSensor(uc, flip)
    if keypad:
        if not shadow:
            raise ValueError('Keypad scan requires shadow-MMIO')
        from keypad import Keypad
        keypad_device = Keypad(uc, keys_file)
        for row, column in press:
            keypad_device.set_key(row, column, True)
    if mmc:
        if not shadow:
            raise ValueError('MMC clock requires shadow-MMIO')
        from mmc_clock import MmcClock
        mmc_device = MmcClock()
        uc.mem_map(mmc_device.BASE, 4096)
        mmc_device.attach(uc)
    if lcd:
        from u880_lcd import U880LcdBus
        panel = U880LcdBus()
        panel.attach(uc)
        panel.live_dir = live_dir
        if live_dir:
            live_dir.mkdir(parents=True, exist_ok=True)
    if nand or nand_image is not None:
        from msm6250_nand import NandController
        controller = NandController(nand_image)
        controller.attach(uc)
    if banks:
        from register_banks import RegisterBanks
        register_banks = RegisterBanks()
        register_banks.attach(uc)
    mapped = {page for lo, hi, _ in uc.mem_regions() for page in range(lo, hi+1, 4096)}
    shadow_pages.update(mapped-pages)
    pages.update(mapped)
    mmio_accesses = {}
    recent = deque(maxlen=32)
    state = {'instructions': 0, 'entry': hex(LOAD), 'stop': 'instruction limit',
             'boot_succeeded': False, 'no_firmware_patches': True, 'accesses': [],
             'shadow_mmio': shadow, 'cpu': 'ARM926', 'target': 'amss'}
    state['ram_reset'] = 'zero-filled approximation' if zero_ram else 'require firmware-initialized bytes'
    state['instruction_count_kind'] = 'block estimate' if block_trace else 'instruction hooks'
    if cstring_entries:
        state['cstring_watch'] = []
        state['cstring_watch_hits'] = 0
        names = dict(r0=UC_ARM_REG_R0, r1=UC_ARM_REG_R1,
                     r2=UC_ARM_REG_R2, r3=UC_ARM_REG_R3)
        def string_observer(register_name):
            def observed(machine, address, size, _):
                pointer = machine.reg_read(names[register_name])
                try:
                    raw = bytes(machine.mem_read(pointer, 128)).split(b'\0')[0]
                    value = raw.decode('ascii') if all(32 <= byte < 127 for byte in raw) else None
                except (UcError, UnicodeDecodeError):
                    value = None
                state['cstring_watch_hits'] += 1
                state['cstring_watch'].append(dict(pc=hex(address), argument=register_name,
                    value=value, pointer=hex(pointer), lr=hex(machine.reg_read(UC_ARM_REG_LR)),
                    instructions=state['instructions']))
                del state['cstring_watch'][:-128]
            return observed
        for entry, register_name in cstring_entries:
            if register_name not in names:
                raise ValueError('CString watch requires r0, r1, r2 or r3')
            uc.hook_add(UC_HOOK_CODE, string_observer(register_name), begin=entry, end=entry)
    if watch_entries:
        state['debug_watch'] = []
        def observe(machine, address, size, _):
            if len(state['debug_watch']) < 128:
                state['debug_watch'].append(dict(pc=hex(address),
                    r0=hex(machine.reg_read(UC_ARM_REG_R0)),
                    r1=hex(machine.reg_read(UC_ARM_REG_R1)),
                    lr=hex(machine.reg_read(UC_ARM_REG_LR)),
                    instructions=state['instructions']))
        for entry in watch_entries:
            uc.hook_add(UC_HOOK_CODE, observe, begin=entry, end=entry)
    debug_pending = debug_session is not None
    debug_active = False
    if debug_pending:
        if debug_at is None or not zero_ram:
            raise ValueError('Native filesystem import requires a breakpoint and mapped scratch RAM')
        def start_debug(machine, address, size, _):
            if debug_pending:
                state['stop'] = 'debugger: start native filesystem import'
                machine.emu_stop()
        uc.hook_add(UC_HOOK_CODE, start_debug, begin=debug_at, end=debug_at)
    timer = None
    if irq:
        from timer_irq import TimerIRQ
        timer = TimerIRQ()
        timer.VECTOR_BASE = LOAD
        timer.attach(uc)
    if keypad_device and timer:
        keypad_device.clock=lambda:timer.cycles/timer.CPU_HZ
    uim_uart = None
    if uim_card:
        from uim_uart import UimUart
        uim_uart = UimUart(uc, timer, atr_poll_pc=None, atr_on_reset=True)
    nand_metadata_trace = deque(maxlen=256)
    if controller is not None:
        def nand_command(machine, access, address, size, value, _):
            if 42*controller.BLOCK <= controller.address < 47*controller.BLOCK:
                nand_metadata_trace.append({'command': value, 'address': hex(controller.address),
                                            'pc': hex(machine.reg_read(UC_ARM_REG_PC)),
                                            'buffer_prefix': bytes(machine.mem_read(controller.BASE, 16)).hex()})
        uc.hook_add(UC_HOOK_MEM_WRITE, nand_command,
                    begin=controller.BASE+0x300, end=controller.BASE+0x303)
    if synthetic_ssikyu:
        if controller is None or page_crypto is None:
            raise ValueError('U880 synthetic SSIKYU requires NAND and a known page crypto profile')
        from ssikyu_crypto import CryptoProbe
        from ssikyu_fixture import initialize
        crypto = CryptoProbe(amss, LOAD, *page_crypto)
        state['synthetic_initial_state'] = initialize(controller, probe=crypto, block=43)
        if synthetic_country is not None:
            from ssikyu_fixture import initialize_country
            state['synthetic_country'] = initialize_country(controller, synthetic_country,
                                                            probe=crypto, block=44)
    elif synthetic_country is not None:
        raise ValueError('Country fixture requires synthetic SSIKYU metadata')
    if fatal_entries:
        import fault_watch
        for entry in fatal_entries:
            fault_watch.attach(uc, state, entry=entry)
    if manager_open_return is not None:
        def manager_opened(machine, address, size, _):
            handle = machine.reg_read(UC_ARM_REG_R0)
            state['phone_manager_open'] = {'path': 'LGAPP/Pxo/PhoneMngr.pxo',
                                            'handle': hex(handle), 'succeeded': handle != 0xffffffff,
                                            'kind': 'original file presence test; not PXO execution'}
            if handle == 0xffffffff:
                state['stop'] = 'debugger: PhoneMngr.pxo missing from emulated filesystem'
                machine.emu_stop()
        uc.hook_add(UC_HOOK_CODE, manager_opened, begin=manager_open_return, end=manager_open_return)
    decoders = {False: Cs(CS_ARCH_ARM, CS_MODE_ARM), True: Cs(CS_ARCH_ARM, CS_MODE_THUMB)}
    block_counts = {}

    def writable(address, size):
        return (0x1800000 <= address and address+size <= 0x5000000) or (0xFFFF2000 <= address and address+size <= 0xFFFF3000)

    def code(machine, address, size, _):
        thumb = bool(machine.reg_read(UC_ARM_REG_CPSR)&32)
        count = 1
        if block_trace:
            key = (address, size, thumb)
            if key not in block_counts:
                block_counts[key] = sum(1 for _ in decoders[thumb].disasm_lite(bytes(machine.mem_read(address, size)), address))
            count = block_counts[key]
        if not fast:
            state['instructions'] += count
        recent.append({'pc': hex(address), 'size': size, 'thumb': thumb})
        if debug_active and address == debug_session.RETURN:
            return
        outside = not LOAD <= address <= end-size
        allowed_dynamic = dynamic_code and 0x1800000 <= address <= 0x4efffff-size
        if outside and allowed_dynamic:
            seen = state.setdefault('dynamic_code_blocks', [])
            if len(seen) < 128:
                seen.append(hex(address))
        if outside and not allowed_dynamic:
            state['stop'] = 'execution outside decoded code'
            machine.emu_stop()
        elif timer and not fast and timer.advance(instructions=count):
            state['stop'] = 'deliver IRQ'
            machine.emu_stop()

    def read(machine, access, address, size, value, _):
        if zero_ram and (address+size <= 0x5000000 or 0xffff2000 <= address and address+size <= 0xffff3000):
            return
        if address & ~4095 in shadow_pages:
            return
        if LOAD <= address and address+size <= end:
            return
        if all(address+i in initialized for i in range(size)):
            return
        state['stop'] = 'read requires uncaptured/uninitialized state'
        state['accesses'].append({'address': hex(address), 'size': size, 'access': 'read'})
        machine.emu_stop()

    def write(machine, access, address, size, value, _):
        if not zero_ram and writable(address, size):
            initialized.update(range(address, address+size))

    def memory(machine, access, address, size, value, _):
        if address & ~4095 in shadow_pages:
            key = (address, access)
            mmio_accesses[key] = mmio_accesses.get(key, 0)+1

    def invalid(machine, access, address, size, value, _):
        if shadow and access in (UC_MEM_WRITE_UNMAPPED, UC_MEM_READ_UNMAPPED) and any(
                lo <= address and address+size <= hi for lo, hi in (
                    (0x30000000, 0x30100000), (0x48000000, 0x48100000),
                    (0x60000000, 0x64000000), (0x80000000, 0x80100000),
                    (0x84000000, 0x84100000))):
            for page in range(address & ~4095, (address+size+4095) & ~4095, 4096):
                if page not in pages:
                    machine.mem_map(page, 4096)
                    pages.add(page)
                    shadow_pages.add(page)
            return True
        if access == UC_MEM_WRITE_UNMAPPED and writable(address, size):
            for page in range(address&~4095, (address+size+4095)&~4095, 4096):
                if page not in pages:
                    machine.mem_map(page, 4096); pages.add(page)
            initialized.update(range(address, address+size))
            return True
        state['stop'] = 'unmodeled hardware or memory access'
        state['accesses'].append({'address': hex(address), 'size': size, 'access_type': access, 'value': hex(value)})
        return False

    trace_hook = None
    if fast:
        # Keep execution guards and dynamic-code observation outside the static
        # firmware while letting Unicorn execute its interior without Python
        # callbacks per block. Hardware memory hooks and breakpoints remain live.
        uc.hook_add(UC_HOOK_BLOCK, code, begin=0, end=LOAD-1)
        uc.hook_add(UC_HOOK_BLOCK, code, begin=end, end=0xffffffff)
    else:
        trace_hook = uc.hook_add(UC_HOOK_BLOCK if block_trace else UC_HOOK_CODE, code)
    if not zero_ram:
        uc.hook_add(UC_HOOK_MEM_READ, read)
        uc.hook_add(UC_HOOK_MEM_WRITE, write)
    for lo, hi in ((0x30000000, 0x30100000), (0x48000000, 0x48100000),
                   (0x60000000, 0x64000000), (0x80000000, 0x80100000),
                   (0x84000000, 0x84100000)):
        uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, memory, begin=lo, end=hi-1)
    uc.hook_add(UC_HOOK_MEM_INVALID, invalid)
    uc.reg_write(UC_ARM_REG_CPSR, 0xD3)
    uc.reg_write(UC_ARM_REG_R12, 0xBC000000)
    start = LOAD
    fast_phase = 0
    checkpoint_config = dict(kind='u880-amss', sha256=hashlib.sha256(amss).hexdigest(),
        shadow=shadow, zero_ram=zero_ram, banks=banks, nand=controller is not None,
        lcd=lcd, mmc=mmc, irq=irq, keypad=keypad, dynamic_code=dynamic_code,
        synthetic_ssikyu=synthetic_ssikyu, synthetic_country=synthetic_country)
    if uim_card:
        checkpoint_config["uim_card"] = True
    if resume:
        if debug_session is not None and not debug_on_resume:
            raise ValueError('A resumed U880 run cannot start a new native import')
        import checkpoint
        def install_shadow(page):
            if page not in pages:
                uc.mem_map(page, 4096)
                pages.add(page)
            shadow_pages.add(page)
        restored = checkpoint.restore(resume, uc, checkpoint_config, controller, panel,
                                      install_shadow, timer=timer, mmc=mmc_device,
                                      keypad=keypad_device)
        if uim_uart and 'uim_uart' in restored.get('extras', {}):
            uim_uart.load(restored['extras']['uim_uart'])
        state['instructions_before_resume'] = restored['instructions_before_resume']
        state['resumed_from'] = str(resume)
        start = uc.reg_read(UC_ARM_REG_PC) | (1 if uc.reg_read(UC_ARM_REG_CPSR)&32 else 0)
    if keypad_device:
        for row,column in press:
            keypad_device.set_key(row,column,True)
    if pxo_watch_profile is not None:
        import pxo_watch
        register_module = pxo_watch.attach(uc, state, **pxo_watch_profile)
        for handle in pxo_handles:
            register_module(handle)
    if panel and live_dir:
        panel.publish("main")
        panel.publish("sub")
    while state['instructions'] < limit:
        if stop_requested and stop_requested():
            state["stop"] = "window requested stop"
            break
        chunked = fast or (debug_active and fast_import)
        chunk_size = 10000 if fast and timer else 100000
        if fast and timer and not timer.inflight and timer.enabled_bits() and uc.reg_read(UC_ARM_REG_CPSR)&0x80:
            # Vary sampling boundaries while a pending IRQ is masked, so a
            # periodic critical section cannot hide every unmasked interval.
            chunk_size = (31, 127, 521, 2053, 8191)[fast_phase % 5]
            fast_phase += 1
        chunk = min(chunk_size, limit-state['instructions']) if chunked else max(1, limit-state['instructions'])
        try:
            uc.emu_start(start, 0x100000000, count=chunk)
        except UcError as error:
            state['unicorn_error'] = str(error)
            if state['stop'] == 'instruction limit':
                state['stop'] = 'CPU exception'

        if chunked:
            state['instructions'] += chunk
            if fast:
                state['instruction_count_kind'] = 'chunk upper bound; up to 10000 with IRQ, 100000 otherwise'
            else:
                state['native_import_instruction_count_kind'] = 'upper bound in 100000 instruction chunks'
                state['instruction_count_kind'] = 'block estimate outside import; chunk upper bound during import'
            if state['stop'] == 'instruction limit' and 'unicorn_error' not in state:
                if fast and timer and timer.advance(instructions=chunk):
                    state['stop'] = 'deliver IRQ'
                else:
                    start = uc.reg_read(UC_ARM_REG_PC) | (1 if uc.reg_read(UC_ARM_REG_CPSR)&32 else 0)
                    continue
        if state['stop'] == 'debugger: start native filesystem import':
            debug_pending = False
            debug_active = True
            debug_session.setup(uc, state)
            if fast_import and trace_hook is not None:
                uc.hook_del(trace_hook)
                uc.ctl_flush_tb()
            state['stop'] = 'instruction limit'
            start = uc.reg_read(UC_ARM_REG_PC) | 1
            continue
        if debug_active and state['stop'] == debug_session.STOP:
            more = debug_session.finish(uc, state)
            if not more:
                debug_active = False
                if fast_import and not fast:
                    trace_hook = uc.hook_add(UC_HOOK_BLOCK if block_trace else UC_HOOK_CODE, code)
                    # Previously cached native FS blocks were translated without
                    # tracing; rebuild them before counting or delivering timers.
                    uc.ctl_flush_tb()
                if not debug_continue:
                    break
                state['debug_session_complete'] = True
                state['debug_session_kind'] = getattr(debug_session, 'KIND', 'native_fs_import')
                if state['debug_session_kind'] == 'native_fs_import':
                    state['native_fs_import_complete'] = True
                if post_import_limit is not None:
                    limit = min(limit, state['instructions']+post_import_limit)
            state['stop'] = 'instruction limit'
            start = uc.reg_read(UC_ARM_REG_PC) | (1 if uc.reg_read(UC_ARM_REG_CPSR)&32 else 0)
            continue
        if state['stop'] != 'deliver IRQ':
            break
        from timer_irq import enter_irq
        if enter_irq(uc, LOAD):
            timer.delivered += 1
            timer.inflight = True
        state['stop'] = 'instruction limit'
        start = uc.reg_read(UC_ARM_REG_PC) | (1 if uc.reg_read(UC_ARM_REG_CPSR)&32 else 0)
    state.update(pc=hex(uc.reg_read(UC_ARM_REG_PC)), sp=hex(uc.reg_read(UC_ARM_REG_SP)),
                 recently_executed=list(recent), initialized_work_bytes=len(initialized))
    state['registers'] = {name: hex(uc.reg_read(reg)) for name, reg in (
        ('r0', UC_ARM_REG_R0), ('r1', UC_ARM_REG_R1), ('r2', UC_ARM_REG_R2), ('r3', UC_ARM_REG_R3),
        ('r4', UC_ARM_REG_R4), ('r5', UC_ARM_REG_R5), ('r6', UC_ARM_REG_R6), ('r7', UC_ARM_REG_R7),
        ('lr', UC_ARM_REG_LR), ('cpsr', UC_ARM_REG_CPSR))}
    if save_checkpoint:
        if debug_active or debug_pending:
            raise ValueError(f"Unfinished native session: PC={uc.reg_read(UC_ARM_REG_PC):#x}, stop={state['stop']}, instructions={state['instructions']}, active={debug_active}, pending={debug_pending}")
        import checkpoint
        save_checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.save(save_checkpoint, uc, checkpoint_config, controller, panel,
                        shadow_pages, state['instructions'], timer=timer,
                        mmc=mmc_device, keypad=keypad_device,
                        extras={'uim_uart': uim_uart.snapshot()} if uim_uart else None)
        state['checkpoint'] = str(save_checkpoint)
    if mmc_device:
        state['mmc'] = mmc_device.report()
    if timer:
        state['timer_irq'] = timer.report()
    if uim_uart:
        state['uim_uart'] = uim_uart.report()
        state['uim_uart']['apdus'] = uim_uart.card.apdus[:500]
    if keypad_device:
        state['keypad'] = keypad_device.report()
    if flip_sensor:
        state['flip_sensor'] = flip_sensor.report()
    state['mmio'] = [{'address': hex(address), 'access_type': access, 'count': count}
                     for (address, access), count in sorted(mmio_accesses.items())]
    if register_banks:
        state['register_banks'] = register_banks.report()
    if controller:
        state['nand'] = controller.report()
        state['nand']['metadata_trace'] = list(nand_metadata_trace)
    if panel:
        state['lcd'] = panel.report()
        if live_dir:
            panel.export(live_dir/'main.ppm')
            panel.export_sub(live_dir/'sub.ppm')
            state['frames_dir'] = str(live_dir)
    if shadow:
        state['limitations'] = ['Diagnostic zero-initialized register storage; peripheral semantics not modeled',
                                'Full handset boot not demonstrated; device models remain experimental']
    if controller:
        state.setdefault('limitations', []).append('Shared MSM6250 NAND model; U880 filesystem layout not validated')
    return state
