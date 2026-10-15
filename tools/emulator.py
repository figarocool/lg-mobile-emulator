"""Experimental U310 ARM926 harness with inferred NAND subset and LCD bus capture."""
import argparse
import json
import os
import hashlib
from collections import Counter, deque
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
from unicorn import *
from unicorn.arm_const import UC_CPU_ARM_926, UC_ARM_REG_CPSR, UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_R0, UC_ARM_REG_LR, UC_ARM_REG_R12
from msm6250_nand import NandController
from lcd_bus import LcdBus
from register_banks import RegisterBanks
import checkpoint
from timer_irq import TimerIRQ, enter_irq
from rex_inspect import inspect_rex
from mmc_clock import MmcClock
import fault_watch
from unicorn import arm_const

ROOT = Path(__file__).resolve().parents[1]
(ROOT / 'analysis').mkdir(exist_ok=True)  # reports, last frame and checkpoints go here
import faulthandler
import signal as _signal
faulthandler.register(_signal.SIGUSR1, all_threads=True)  # kill -USR1 <pid>: where is the emulator right now?

FAST_CHUNK = int(os.environ.get('U310_CHUNK', 20000))
SLEEP_LOOP = 0x10dbd26
SLEEP_TCB = 0x1bf8fe0
REX_CURRENT_TCB = 0x019a3f18


def write_nand_state(path, controller):
    """Flash contents in the format read by --nand-from-checkpoint (atomic replace, previous state kept as .bak)."""
    import zipfile
    path = Path(path)
    temp = path.with_suffix('.tmp')
    metadata = {'nand': {key: getattr(controller, key) for key in
                         ['synthetic', 'address', 'config', 'status', 'pending', 'spare_word',
                          'direct_command', 'direct_status_reads', 'factory_fixture']}}
    with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        z.writestr('metadata.json', json.dumps(metadata))
        z.writestr('nand.bin', controller.storage)
        z.writestr('nand_spare.bin', controller.spare)
    if path.exists():
        path.replace(path.with_suffix('.bak'))
    temp.replace(path)


def run(target='boot', shadow=False, limit=100000, nand=False, nand_image=None, lcd=False,
        banks=False, save_checkpoint=None, resume=None, irq=False, mmc=False, block_trace=False,
        synthetic_ssikyu=False, mdsp_management=False, keypad=False, flip=None, press=(), keys_file=None, live_dir=None, nand_checkpoint=None, uim_card=False, release_keys=False, fast=False, realtime=False, cpu_mhz=None, audio=False, imei=None, bt_addr=None, save_nand=None, save_nand_after=0, rf_defaults=False, netsim=False, debug_setup=None, debug_finish=None):
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    uc.ctl_set_cpu_model(UC_CPU_ARM_926)
    if target == 'amss':
        uc.mem_map(0, 0x01000000)
    uc.mem_map(0x01000000, 0x04000000)
    uc.mem_map(0xffff0000, 0x10000)
    boot = (ROOT / 'firmware/BOOT_LOADER_U310.bin').read_bytes()
    uc.mem_write(0xffff0000, boot)
    controller = None
    register_banks = RegisterBanks() if banks else None
    if register_banks:
        register_banks.attach(uc)
    panel = LcdBus() if lcd else None
    if panel:
        panel.attach(uc)
        panel.live_dir = live_dir
    if nand:
        controller = NandController(nand_image)
        if nand_checkpoint:
            # Cold boot of the CPU over the flash contents saved in a checkpoint.
            import zipfile
            with zipfile.ZipFile(nand_checkpoint) as z:
                controller.storage[:] = z.read('nand.bin')
                controller.spare[:] = z.read('nand_spare.bin')
                saved = json.loads(z.read('metadata.json'))['nand']
            controller.synthetic = saved['synthetic']
            controller.factory_fixture = saved.get('factory_fixture', controller.factory_fixture)
        controller.attach(uc)
    timer = TimerIRQ() if irq else None
    if timer and cpu_mhz:
        timer.CPU_HZ = int(cpu_mhz * 1_000_000)
    if timer:
        timer.attach(uc)
    sd_card_model = None
    if mmc and os.environ.get('U310_SD'):
        from mmc_card import SdCard
        from mmc_controller import MmcController
        sd_card_model = SdCard(os.environ['U310_SD'])
        mmc_device = MmcController(sd_card_model)
    else:
        mmc_device = MmcClock() if mmc else None
    if mmc_device:
        mmc_device.attach(uc)
    dsp_management = None
    keypad_device = None
    if keypad:
        if not shadow:
            raise ValueError('Keypad scan requires shadow-MMIO')
        from keypad import Keypad
        keypad_device = Keypad(uc, keys_file, (lambda: timer.cycles / timer.CPU_HZ) if timer else None)
        for row, column in press:
            keypad_device.set_key(row, column, True)
    if mdsp_management:
        if target != 'amss' or not banks or not irq:
            raise ValueError('MDSP management requires AMSS, register banks and timer IRQ')
        from mdsp_management import MdspManagement
        dsp_management = MdspManagement(uc, timer, qdsp=audio)
    if target == 'amss':
        data = next((ROOT / 'firmware').glob('*CODE*')).read_bytes()[0x24000:]
        # Candidate relocation delta +0x38000 supported by string references and vectors.
        uc.mem_write(0x0005c000, data)
        start = 0x0005c000
        uc.reg_write(UC_ARM_REG_R12, 0xbc000000)
    elif target in ('code', 'nand-init'):
        data = next((ROOT / 'firmware').glob('*CODE*')).read_bytes()[0x4000:]
        uc.mem_write(0x02200000, data)
        start = 0x02200000
        uc.reg_write(UC_ARM_REG_SP, 0x04fff000)
        if target == 'nand-init':
            start = 0x02202768
            uc.reg_write(UC_ARM_REG_R0, 0x02b00000)
            uc.reg_write(UC_ARM_REG_LR, 0x04ffe000)
            uc.mem_write(0x04ffe000, bytes.fromhex('feffffea'))
    else:
        start = 0xffff0000
    uc.reg_write(UC_ARM_REG_CPSR, 0xd3)
    decoders = {False: Cs(CS_ARCH_ARM, CS_MODE_ARM), True: Cs(CS_ARCH_ARM, CS_MODE_THUMB)}
    recent = deque(maxlen=64)
    hits = Counter()
    mmio = Counter()
    mmio_census = Counter() if os.environ.get('U310_MMIO_CENSUS') else None
    pages = set()
    state = {'instructions': 0, 'stop': 'instruction limit', 'target': target,
             'shadow_mmio': shadow, 'cpu': 'ARM926', 'load_map_verified': False,
             'instruction_count_kind': 'block estimate' if block_trace else 'instruction hooks'}
    config = {'target': target, 'shadow': shadow, 'nand': bool(nand), 'lcd': lcd, 'banks': banks,
              'firmware': hashlib.sha256(next((ROOT/'firmware').glob('*CODE*')).read_bytes()).hexdigest(),
              'irq': irq, 'mmc': mmc}
    if mdsp_management:
        config['mdsp_management'] = True
    uim_uart = None
    if uim_card:
        from uim_uart import UimUart
        uim_uart = UimUart(uc, timer)
    flip_sensor = None
    if flip is not None:
        from gpio_inputs import FlipSensor
        flip_sensor = FlipSensor(uc, flip)
    if keypad:
        config['keypad'] = True

    census_installed = []

    def install_shadow(page):
        if page in pages:
            return  # already mapped up front (MMC page) or restored
        uc.mem_map(page, 0x1000)
        pages.add(page)
        if not census_installed:
            # One hook per hardware window instead of one per page: every extra memory hook is
            # scanned on each guest load/store, so dozens of per-page hooks slow the whole CPU.
            # The MMC controller page (0x61800000) is left out of the census: the firmware polls its status
            # register millions of times waiting for a card, and a Python callback per read costs minutes.
            for lo, hi in ((0x30000000, 0x30100000), (0x48000000, 0x48100000), (0x60000000, 0x61800000),
                           (0x61801000, 0x64000000), (0x80000000, 0x80100000), (0x84000000, 0x84100000)):
                uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, memory, begin=lo, end=hi - 1)
            census_installed.append(True)

    def instruction(u, address, size, _):
        instructions = [(address, size, bool(u.reg_read(UC_ARM_REG_CPSR) & 32))]
        if block_trace:
            raw = bytes(u.mem_read(address, size))
            thumb = instructions[0][2]
            key = (address, raw, thumb)
            if key not in block_cache:
                block_cache[key] = [(i.address, i.size, thumb) for i in decoders[thumb].disasm(raw, address)]
            instructions = block_cache[key] or instructions
        state['instructions'] += len(instructions)
        for item in instructions:
            if not recent or recent[-1][0] != item[0]:
                recent.append(item)
        hits['consecutive'] = hits['consecutive'] + 1 if hits['previous'] == address else 1
        hits['previous'] = address
        if dsp_management:
            dsp_management.advance()
        # The SLEEP task polling loop is the firmware idle loop: waiting for the next
        # timer tick is equivalent to a CPU wait-for-interrupt, no guest code is skipped.
        sleeping = (address == SLEEP_LOOP and block_trace and
                    int.from_bytes(u.mem_read(REX_CURRENT_TCB, 4), 'little') == SLEEP_TCB)
        if timer and timer.advance(idle=sleeping or hits['consecutive'] >= 64 and len(instructions) == 1,
                                   instructions=len(instructions)):
            state['stop'] = 'deliver IRQ'
            u.emu_stop()
            return
        if hits['consecutive'] == 64 and len(instructions) == 1:
            state['stop'] = f'self branch at 0x{address:08x}'
            u.emu_stop()

    def invalid(u, access, address, size, value, _):
        state['last_unmapped'] = dict(access=access, address=hex(address), size=size, value=hex(value))
        # Never synthesize executable memory or an unknown peripheral outside these windows.
        if shadow and access in (UC_MEM_READ_UNMAPPED, UC_MEM_WRITE_UNMAPPED) and any(
            lo <= address < hi for lo, hi in [(0x30000000, 0x30100000),
                (0x48000000, 0x48100000), (0x60000000, 0x64000000),
                (0x80000000, 0x80100000), (0x84000000, 0x84100000)]):
            page = address & ~0xfff
            install_shadow(page)
            return True
        return False

    def memory(u, access, address, size, value, _):
        if address & ~0xfff in pages:
            mmio[(address, 'read' if access == UC_MEM_READ else 'write')] += 1
            if mmio_census is not None:
                mmio_census[(hex(address), 'r' if access == UC_MEM_READ else 'w', hex(u.reg_read(UC_ARM_REG_PC)))] += 1

    if mmc_device:
        mmc_device.map_page = install_shadow
        if MmcClock.BASE not in pages:
            install_shadow(MmcClock.BASE)  # mapped up front: the clock model only hooks writes (see mmc_clock.py)

    block_cache = {}
    if not fast:
        uc.hook_add(UC_HOOK_BLOCK if block_trace else UC_HOOK_CODE, instruction)
    uc.hook_add(UC_HOOK_MEM_INVALID, invalid)
    if target == 'amss':
        fault_watch.attach(uc, state)
        # Diagnostic observers cost a Python callback per block or memory access; fast mode (the
        # interactive emulator) leaves them out. U310_WATCH=1 puts them back even in fast mode.
        if not fast or os.environ.get('U310_WATCH'):
            import startup_watch
            startup_watch.attach(uc, state)
            import native_api_watch
            native_api_watch.attach(uc, state)
            import gpio_watch
            gpio_watch.attach(uc, state)
            import rex_signal_watch
            rex_signal_watch.attach(uc, state)
            import uim_watch
            uim_watch.attach(uc, state)
            import pxo_watch
            pxo_watch.attach(uc, state)
        identity = {}
        if imei:
            import nv_override
            identity[nv_override.NV_UE_IMEI] = nv_override.imei_nv(imei)
        if bt_addr:
            import nv_override
            identity[nv_override.NV_BD_ADDR] = nv_override.bd_addr_nv(bt_addr)
        if identity or rf_defaults:
            import nv_override
            zero_items = ()
            if rf_defaults:
                from rf_nv_items import ITEMS as zero_items
            nv_override_device = nv_override.NvOverride(uc, identity, zero_items)
            state['nv_override'] = nv_override_device
        if os.environ.get('U310_PC_HITS'):
            pc_hits = {}
            state['pc_hits'] = pc_hits
            def hit(u, address, size, _):
                entry = pc_hits.setdefault(hex(address), {'n': 0, 'lr': [], 'regs': []})
                entry['n'] += 1
                if len(entry['lr']) < 3000:
                    entry['lr'].append(hex(u.reg_read(arm_const.UC_ARM_REG_LR)))
                    entry['regs'].append([hex(u.reg_read(r)) for r in (arm_const.UC_ARM_REG_R0, arm_const.UC_ARM_REG_R1)])
                    try:
                        raw = bytes(u.mem_read(u.reg_read(arm_const.UC_ARM_REG_R0), 120))
                        entry.setdefault('text', []).append(raw.decode('utf-16-le', 'ignore').split('\0')[0])
                    except Exception:
                        pass
                    try:
                        raw = bytes(u.mem_read(u.reg_read(arm_const.UC_ARM_REG_R1), 80)).split(b'\0')[0]
                        entry.setdefault('ascii1', []).append(raw.decode('latin1') if all(32 <= c < 127 for c in raw) else '')
                    except Exception:
                        pass
            for item in os.environ['U310_PC_HITS'].split(','):
                uc.hook_add(UC_HOOK_CODE, hit, begin=int(item, 16), end=int(item, 16))
        if os.environ.get('U310_TASK_MMIO'):
            task_mmio = {}
            state['task_mmio'] = task_mmio
            wanted = {int(t, 16) for t in os.environ['U310_TASK_MMIO'].split(',')}
            def mmio_access(u, access, address, size, value, _):
                tcb = int.from_bytes(u.mem_read(0x19a3f18, 4), 'little')
                if tcb in wanted:
                    key = ('w' if access else 'r', hex(address), hex(u.reg_read(arm_const.UC_ARM_REG_PC)))
                    task_mmio[key] = task_mmio.get(key, 0) + 1
            for lo, hi in ((0x30000000, 0x3fffffff), (0x48000000, 0x4fffffff), (0x60000000, 0x6fffffff), (0x80000000, 0x8fffffff)):
                uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, mmio_access, begin=lo, end=hi)
        if os.environ.get('U310_WATCH_WRITES'):
            write_log = []
            state['write_log'] = write_log
            def watch_write(u, access, address, size, value, _):
                if len(write_log) < 400:
                    write_log.append([hex(address), size, hex(value & 0xffffffff), hex(u.reg_read(arm_const.UC_ARM_REG_PC)), hex(u.reg_read(arm_const.UC_ARM_REG_LR))])
            for item in os.environ['U310_WATCH_WRITES'].split(','):
                lo, _, hi = item.partition('-')
                uc.hook_add(UC_HOOK_MEM_WRITE, watch_write, begin=int(lo, 16), end=int(hi or lo, 16))
        if os.environ.get('U310_WATCH_ACCESS'):
            access_log = []
            state['access_log'] = access_log
            def watch_access(u, access, address, size, value, _):
                if len(access_log) < int(os.environ.get('U310_WATCH_LIMIT', 800)):
                    access_log.append(['w' if access else 'r', hex(address), size, hex(value & 0xffffffff) if access else '',
                                       hex(u.reg_read(arm_const.UC_ARM_REG_PC))])
            for item in os.environ['U310_WATCH_ACCESS'].split(','):
                lo, _, hi = item.partition('-')
                uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, watch_access, begin=int(lo, 16), end=int(hi or lo, 16))
        if os.environ.get('U310_NV_LOG'):
            nv_log = {}
            state['nv_log'] = nv_log
            def log_nv(u, address, size, _):
                cmd = u.reg_read(arm_const.UC_ARM_REG_R0)
                key = (int.from_bytes(u.mem_read(cmd + 4, 2), 'little'), int.from_bytes(u.mem_read(cmd + 6, 2), 'little'),
                       hex(u.reg_read(arm_const.UC_ARM_REG_LR)))
                nv_log[key] = nv_log.get(key, 0) + 1
            uc.hook_add(UC_HOOK_CODE, log_nv, begin=0x10d219a, end=0x10d219a)
        netsim_device = None
        if netsim:
            from netsim import Network
            netsim_device = Network(uc)
            state['netsim'] = netsim_device
        if audio:
            import audio_hle
            audio_output = audio_hle.attach(uc, state, dsp_management)
        import entry_watch
        entry_watch.attach(uc, state)
        import task_coverage
        task_coverage.attach(uc, state)
        import msg_watch
        msg_watch.attach(uc, state)
        import atr_trace
        atr_trace.attach(uc, state)
    if resume:
        restored = checkpoint.restore(resume, uc, config, controller, panel, install_shadow, timer, mmc_device, dsp_management, keypad_device)
        start = uc.reg_read(UC_ARM_REG_PC) | (1 if uc.reg_read(UC_ARM_REG_CPSR) & 32 else 0)
        state['instructions_before_resume'] = restored['instructions_before_resume']
        if panel and live_dir:
            panel.publish('main')  # show the saved screens immediately, before the first new frame
            panel.publish('sub')
        if release_keys and keypad_device:
            keypad_device.pressed.clear()  # a checkpoint restores held keys; this forces a release
        if uim_uart and 'uim_uart' in restored.get('extras', {}):
            uim_uart.load(restored['extras']['uim_uart'])
    if synthetic_ssikyu:
        if controller is None:
            raise ValueError('Synthetic SSIKYU requires --nand')
        from ssikyu_fixture import initialize
        state['synthetic_initial_state'] = initialize(controller)
    if debug_setup:
        debug_setup(uc, state)
        start = uc.reg_read(UC_ARM_REG_PC) | (1 if uc.reg_read(UC_ARM_REG_CPSR) & 32 else 0)
    import time
    profile = Counter() if os.environ.get('U310_FAST_PROFILE') else None
    masked_pending, retry_chunks = False, (13, 29, 41, 53, 67, 79, 97)
    wall_start, cycles_start = time.monotonic(), timer.cycles if timer else 0
    stop_requested = []
    netsim_device = locals().get('netsim_device')
    heartbeat = float(os.environ.get('U310_HEARTBEAT', 0))  # seconds between progress lines (0 = off)
    last_beat = [0.0]
    beat_stats = [0, 0.0]  # chunks and slowest emu_start since the last progress line
    if save_nand:
        import signal
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop_requested.append(True))
    while state['instructions'] < limit:
        if stop_requested:
            state['stop'] = 'terminated by signal'
            break
        if netsim_device and netsim_device.busy():
            netsim_device.service()
        if heartbeat and time.monotonic() - last_beat[0] >= heartbeat:
            last_beat[0] = time.monotonic()
            print(f'[{time.monotonic() - wall_start:6.1f}s] {state["instructions"]} instructions, PC=0x{uc.reg_read(UC_ARM_REG_PC):x}, '
                  f'{beat_stats[0]} chunks, slowest {beat_stats[1]*1000:.0f} ms', flush=True)
            beat_stats[:] = [0, 0.0]
        state['stop'] = 'instruction limit'
        chunk = limit-state['instructions']
        if fast:
            # While an interrupt waits behind a masked CPSR I-bit, step in small, varying chunks so a
            # periodic INTLOCK/INTFREE loop cannot hide the unmasked window from every chunk boundary.
            chunk = min(retry_chunks[state['instructions'] % 7] if masked_pending else FAST_CHUNK, chunk)
        try:
            if heartbeat:
                call_start = time.monotonic()
            uc.emu_start(start, 0, count=chunk)
            if heartbeat:
                beat_stats[0] += 1
                beat_stats[1] = max(beat_stats[1], time.monotonic() - call_start)
        except UcError as exc:
            state['stop'] = str(exc)
        if fast and state['stop'] == 'instruction limit':
            # Fast mode: no Python hook per block. Time advances by whole chunks, the idle task
            # waits for the next tick (like a wait-for-interrupt) and delivery happens between chunks.
            state['instructions'] += chunk
            if dsp_management:
                dsp_management.advance()
            cpsr = uc.reg_read(UC_ARM_REG_CPSR)
            if profile is not None:
                profile[(hex(uc.reg_read(UC_ARM_REG_PC)), hex(cpsr & 0x1f), hex(int.from_bytes(uc.mem_read(REX_CURRENT_TCB, 4), 'little')))] += 1
            idle = (cpsr & 0x1f == 0x1f and not cpsr & 0x80 and
                    int.from_bytes(uc.mem_read(REX_CURRENT_TCB, 4), 'little') == SLEEP_TCB)
            if timer and timer.advance(idle=idle, instructions=chunk):
                state['stop'] = 'deliver IRQ'
                masked_pending = False
            else:
                masked_pending = bool(timer and not timer.inflight and timer.enabled_bits() and cpsr & 0x80)
                start = uc.reg_read(UC_ARM_REG_PC) | (1 if cpsr & 32 else 0)
                if realtime and timer:
                    ahead = (timer.cycles - cycles_start) / timer.CPU_HZ - (time.monotonic() - wall_start)
                    if ahead > 0:
                        time.sleep(min(ahead, 0.05))
                continue
        if state['stop'] != 'deliver IRQ':
            if debug_finish and debug_finish(uc, state):
                start = uc.reg_read(UC_ARM_REG_PC) | (1 if uc.reg_read(UC_ARM_REG_CPSR) & 32 else 0)
                hits['consecutive'] = 0
                continue
            break
        bits = timer.enabled_bits()
        source = str((bits & -bits).bit_length()-1)
        if enter_irq(uc, timer.VECTOR_BASE):
            timer.delivered += 1
            timer.delivered_sources[source] = timer.delivered_sources.get(source, 0) + 1
            timer.inflight = True
        start = uc.reg_read(UC_ARM_REG_PC)
        hits['consecutive'] = 0
    if save_nand and controller and state['instructions'] + state.get('instructions_before_resume', 0) >= save_nand_after:
        write_nand_state(save_nand, controller)
        state['nand_saved'] = str(save_nand)
    if audio and target == 'amss':
        state['audio_report'] = {'tones_started': audio_output.tones_started, 'player': bool(audio_output.process),
                                 'file_requests': audio_output.requests, 'raw_requests': audio_output.raw_requests, 'files_started': audio_output.files.started,
                                 'files_skipped': audio_output.files.skipped}
        audio_output.close()
    state['pc'] = hex(uc.reg_read(UC_ARM_REG_PC))
    if profile is not None:
        state['fast_profile'] = [list(k) + [v] for k, v in profile.most_common(25)]
    state['registers'] = {f'r{i}': hex(uc.reg_read(getattr(arm_const, f'UC_ARM_REG_R{i}')))
                          for i in range(13)}
    state['registers'].update(sp=hex(uc.reg_read(UC_ARM_REG_SP)),
                              cpsr=hex(uc.reg_read(UC_ARM_REG_CPSR)))
    state['trace'] = []
    for address, size, thumb in recent:
        ins = next(decoders[thumb].disasm(bytes(uc.mem_read(address, size)), address), None)
        state['trace'].append(f'{address:08x}: {ins.mnemonic} {ins.op_str}' if ins else hex(address))
    if mmio_census is not None:
        state['mmio_census'] = [list(k) + [v] for k, v in mmio_census.items()]
    state['mmio'] = [{'address': hex(a), 'operation': op, 'count': count}
                     for (a, op), count in mmio.most_common()]
    state['hardware_models_implemented'] = ['NAND controller subset'] if controller else []
    if timer:
        state['hardware_models_implemented'].append('IRQ0 timer subset with candidate vector relocation')
    if mmc_device:
        state['hardware_models_implemented'].append('MMC clock start/stop subset')
    if target == 'amss':
        state['rex'] = inspect_rex(uc)
        if not fast or os.environ.get('U310_WATCH'):
            startup_watch.finalize(state)
            gpio_watch.finalize(state)
            rex_signal_watch.finalize(state)
            uim_watch.finalize(state)
        entry_watch.finalize(state)
        task_coverage.finalize(state)
        msg_watch.finalize(state)
        if 'netsim' in state:
            state['netsim'] = state['netsim'].report()
        if 'nv_override' in state:
            state['nv_override'] = state['nv_override'].report()
        if 'access_log' in state:
            pass
        if 'task_mmio' in state:
            state['task_mmio'] = [[k[0], k[1], k[2], v] for k, v in sorted(state['task_mmio'].items())]
        if 'nv_log' in state:
            state['nv_log'] = [[k[0], k[1], k[2], v] for k, v in sorted(state['nv_log'].items())]
        state['cp15'] = {str(crn): hex(uc.reg_read(arm_const.UC_ARM_REG_CP_REG,
                         (15, 0, 0, crn, 0, 0, 0))) for crn in (1, 2, 3, 13)}
    if register_banks:
        state['register_banks'] = register_banks.report()
        if target == 'amss':
            from mdsp_inspect import inspect_mdsp
            state['mdsp_state'] = inspect_mdsp(uc)
    if controller:
        state['nand'] = controller.report()
    if timer:
        state['timer_irq'] = timer.report()
    if mmc_device:
        state['mmc_clock'] = mmc_device.report()
    if dsp_management:
        state['mdsp_management'] = dsp_management.report()
    if uim_uart:
        state['uim_uart'] = uim_uart.report()
    if flip_sensor:
        state['flip_sensor'] = flip_sensor.report()
    if keypad_device:
        state['keypad'] = keypad_device.report()
        state['hardware_models_implemented'].append('5x7 keypad scan subset')
    if panel:
        state['lcd_bus'] = panel.report()
        if panel.sub_frames:
            panel.export_sub(ROOT / 'analysis' / f'{target}_sub_lcd.ppm')
        if panel.pixel_writes:
            screen = ROOT / 'analysis' / f'{target}_lcd.ppm'
            panel.export(screen)
            state['lcd_bus']['screen'] = str(screen)
        state['framebuffers'] = []
        for name, address, width, height in [('main', 0x02385d20, 176, 220),
                                             ('sub', 0x02398ba0, 96, 96)]:
            raw = bytes(uc.mem_read(address, width*height*2))
            out = ROOT / 'analysis' / f'{target}_{name}_framebuffer.raw'
            out.write_bytes(raw)
            state['framebuffers'].append({'file': str(out), 'address': hex(address),
                'width': width, 'height': height, 'nonzero_bytes': sum(x != 0 for x in raw),
                'note': 'Raw 16-bit RAM buffer inferred from drawing routines; not a verified displayed frame'})
    if target == 'nand-init':
        state['return_value'] = hex(uc.reg_read(UC_ARM_REG_R0))
        state['device_structure'] = bytes(uc.mem_read(0x02b00000, 0x90)).hex()
    if save_checkpoint:
        checkpoint.save(save_checkpoint, uc, config, controller, panel, pages,
                        state['instructions'] + state.get('instructions_before_resume', 0), timer, mmc_device, dsp_management, keypad_device,
                        extras={'uim_uart': uim_uart.snapshot()} if uim_uart else None)
        state['checkpoint'] = str(save_checkpoint)
    return state

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=['boot', 'code', 'nand-init', 'amss'], default='boot')
    parser.add_argument('--nand', action='store_true', help='Enable inferred NAND controller subset')
    parser.add_argument('--register-banks', action='store_true', help='Diagnostic storage for observed 0x58c/0x50c register banks')
    parser.add_argument('--timer-irq', action='store_true', help='Experimental IRQ0 timer and candidate vector relocation (AMSS only)')
    parser.add_argument('--mmc-clock', action='store_true', help='Inferred MMC clock start/stop subset; requires shadow-MMIO')
    parser.add_argument('--block-trace', action='store_true', help='Faster basic-block tracing; counts and IRQ timing are estimates')
    parser.add_argument('--synthetic-ssikyu', action='store_true', help='Initialize erased candidate pages with synthetic empty factory metadata; never a real NAND dump')
    parser.add_argument('--mdsp-management', action='store_true', help='Experimental HLE command-1 management reply; no DSP execution')
    parser.add_argument('--flip', choices=['open', 'closed'], help='Inferred flip sensor state (bit 2 of 0x48000060); hypothesis')
    parser.add_argument('--press', action='append', default=[], metavar='ROW,COL', help='Hold a keypad matrix key (row 0..4, column 0..6) for the whole run')
    parser.add_argument('--keys-file', type=Path, help='File with held ROW,COL pairs, re-read while running (live input)')
    parser.add_argument('--live-dir', type=Path, help='Directory where completed main/sub frames are published as PPM while running')
    parser.add_argument('--nand-from-checkpoint', type=Path, help='Cold boot (no resume) using the NAND stored in this checkpoint')
    parser.add_argument('--uim-card', action='store_true', help='Inferred UIM UART with a minimal USIM model (experimental)')
    parser.add_argument('--release-keys', action='store_true', help='Release all keys right after a checkpoint is restored')
    parser.add_argument('--fast', action='store_true', help='No Python hook per block: run in chunks, much faster (needs --timer-irq)')
    parser.add_argument('--realtime', action='store_true', help='With --fast: do not run faster than the emulated clock')
    parser.add_argument('--cpu-mhz', type=float, help='Emulated clock: instructions per emulated second (default 180). Keep it near what the host can execute for real-time pacing')
    parser.add_argument('--audio', action='store_true', help='Render the phone sound service on the host audio device (tones; experimental)')
    parser.add_argument('--imei', help='IMEI served to the firmware (14 digits, or 15 with check digit)')
    parser.add_argument('--bt-addr', help='Bluetooth address served to the firmware (AA:BB:CC:DD:EE:FF)')
    parser.add_argument('--save-nand', type=Path, help='Write the flash contents here when the run ends (also on SIGTERM/SIGINT)')
    parser.add_argument('--save-nand-after', type=int, default=0, help='Only save the flash when at least this many instructions ran (avoids saving a half-booted phone)')
    parser.add_argument('--rf-defaults', action='store_true', help='Serve zero-filled records for the radio calibration NV items a blank NV lacks')
    parser.add_argument('--netsim', action='store_true', help='Simulated radio network below the NAS (replaces RRC/L1; experimental)')
    parser.add_argument('--sd', type=Path, help='microSD image inserted in the phone (the card controller is not emulated yet)')
    parser.add_argument('--sim', help='SIM profile name (see sim_profile.py); its writes are persisted')
    parser.add_argument('--keypad', action='store_true', help='Inferred idle 5x7 keypad matrix, no keypad IRQ or labeled controls')
    parser.add_argument('--save-checkpoint', type=Path)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--lcd-bus', action='store_true', help='Capture LCD bus and raw drawing buffers; no verified panel emulation')
    parser.add_argument('--nand-image', type=Path, help='Raw 64 MiB NAND image; implies --nand')
    parser.add_argument('--shadow-mmio', action='store_true', help='Zero-initialized register storage; diagnostic only')
    parser.add_argument('--limit', type=int, default=100000)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    if args.timer_irq and args.target != 'amss':
        parser.error('--timer-irq requires --target amss')
    if args.mmc_clock and not args.shadow_mmio:
        parser.error('--mmc-clock requires --shadow-mmio')
    if args.target == 'nand-init' and not (args.nand or args.nand_image):
        parser.error('nand-init requires --nand or --nand-image')
    if args.sim:
        os.environ['U310_SIM'] = args.sim
    if args.sd:
        os.environ['U310_SD'] = str(args.sd)
    result = run(args.target, args.shadow_mmio, args.limit, args.nand or args.nand_image is not None,
                 args.nand_image.read_bytes() if args.nand_image else None, args.lcd_bus,
                 args.register_banks, args.save_checkpoint, args.resume, args.timer_irq, args.mmc_clock, args.block_trace,
                 args.synthetic_ssikyu, args.mdsp_management, args.keypad,
                 None if args.flip is None else args.flip == 'open',
                 [tuple(int(v) for v in item.split(',')) for item in args.press],
                 args.keys_file, args.live_dir, args.nand_from_checkpoint, args.uim_card, args.release_keys, args.fast, args.realtime, args.cpu_mhz, args.audio, args.imei, args.bt_addr, args.save_nand, args.save_nand_after, args.rf_defaults, args.netsim)
    suffix = '_nand' if args.nand or args.nand_image else ''
    suffix += '_lcd' if args.lcd_bus else ''
    suffix += '_banks' if args.register_banks else ''
    suffix += '_irq' if args.timer_irq else ''
    suffix += '_mmc' if args.mmc_clock else ''
    suffix += '_blocks' if args.block_trace else ''
    suffix += '_fixture' if args.synthetic_ssikyu else ''
    suffix += '_mdsp_hle' if args.mdsp_management else ''
    suffix += '_keypad' if args.keypad else ''
    out = ROOT / 'analysis' / f'{args.target}_{"shadow" if args.shadow_mmio else "strict"}{suffix}.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + '\n')
    qualifier = 'estimated ' if args.block_trace else ''
    print(f'{result["instructions"]} {qualifier}instructions; PC={result["pc"]}; stop={result["stop"]}')
    print(f'Report: {out}')
