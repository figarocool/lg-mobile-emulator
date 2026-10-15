"""Local version-locked Unicorn snapshots. JSON and bytes, without pickle."""
import json
import zipfile
from collections import Counter, deque
from unicorn import __version__, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.unicorn_py3.unicorn import UcContext

def save(path, uc, config, controller, panel, pages, instructions, timer=None, mmc=None, mdsp=None, keypad=None, extras=None):
    metadata = {'version': __version__, 'config': config, 'shadow_pages': sorted(pages),
                'instructions_before_resume': instructions, 'regions': []}
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        z.writestr('cpu.bin', bytes(uc.context_save()))
        for index, (begin, end, perms) in enumerate(uc.mem_regions()):
            name = f'memory/{index}.bin'
            metadata['regions'].append([begin, end, perms, name])
            z.writestr(name, bytes(uc.mem_read(begin, end-begin+1)))
        if controller:
            z.writestr('nand.bin', controller.storage)
            z.writestr('nand_spare.bin', controller.spare)
            metadata['nand'] = {key: getattr(controller, key) for key in
                ['synthetic', 'address', 'config', 'status', 'pending', 'spare_word',
                 'direct_command', 'direct_status_reads', 'factory_fixture']}
            metadata['nand']['commands'] = dict(controller.commands)
            metadata['nand']['unsupported'] = dict(controller.unsupported)
        if panel:
            metadata['lcd'] = {key: getattr(panel, key) for key in
                ['selected', 'sub_selected', 'registers', 'sub_registers']}
            metadata['lcd']['counts'] = dict(panel.counts)
            metadata['lcd']['events'] = list(panel.events)
            metadata['lcd']['x'] = panel.x
            metadata['lcd']['y'] = panel.y
            metadata['lcd']['pixel_writes'] = panel.pixel_writes
            metadata['lcd']['history_complete'] = panel.history_complete
            z.writestr('lcd_pixels.bin', panel.pixels)
            z.writestr('lcd_sub_pixels.bin', panel.sub_pixels)
        if timer:
            metadata['timer'] = {key: getattr(timer, key) for key in
                ['cycles', 'deadline', 'period', 'pending', 'raised', 'delivered', 'acks', 'fast_forwards', 'inflight', 'peripheral_pending', 'delivered_sources']}
        if mmc:
            metadata['mmc'] = mmc.snapshot() if hasattr(mmc, 'snapshot') else {key: getattr(mmc, key) for key in ['stopped', 'starts', 'stops']}
        if mdsp:
            metadata['mdsp_management'] = {key: getattr(mdsp, key) for key in
                ['doorbell', 'reset_seen', 'boot_pending', 'boot_replies']}
            metadata['mdsp_management']['completed'] = dict(mdsp.completed)
            metadata['mdsp_management']['unsupported'] = dict(mdsp.unsupported)
        if keypad:
            metadata['keypad'] = {'pressed': sorted(keypad.pressed), 'reads': keypad.reads}
        if extras:
            metadata['extras'] = extras
        z.writestr('metadata.json', json.dumps(metadata))

def restore(path, uc, config, controller, panel, install_shadow, timer=None, mmc=None, mdsp=None, keypad=None):
    with zipfile.ZipFile(path) as z:
        metadata = json.loads(z.read('metadata.json'))
        saved_config = dict(metadata['config'])
        current_config = dict(config)
        # Enabling an additional timer model is allowed for an existing checkpoint.
        saved_irq = saved_config.pop('irq', False)
        current_irq = current_config.pop('irq', False)
        saved_mmc = saved_config.pop('mmc', False)
        current_mmc = current_config.pop('mmc', False)
        saved_mdsp = saved_config.pop('mdsp_management', False)
        current_mdsp = current_config.pop('mdsp_management', False)
        saved_keypad = saved_config.pop('keypad', False)
        current_keypad = current_config.pop('keypad', False)
        if metadata['version'] != __version__ or saved_config != current_config or saved_irq and not current_irq or saved_mmc and not current_mmc or saved_mdsp and not current_mdsp or saved_keypad and not current_keypad:
            raise ValueError('Checkpoint requires identical Unicorn version, firmware and run configuration')
        for page in metadata['shadow_pages']:
            install_shadow(page)
        existing = {(b, e, p) for b, e, p in uc.mem_regions()}
        for begin, end, perms, name in metadata['regions']:
            if (begin, end, perms) not in existing:
                raise ValueError(f'Unexpected checkpoint mapping: {begin:x}-{end:x}')
            data = z.read(name)
            if len(data) != end-begin+1:
                raise ValueError('Checkpoint region length mismatch')
            uc.mem_write(begin, data)
        if controller:
            storage = z.read('nand.bin')
            if len(storage) != controller.SIZE:
                raise ValueError('Invalid checkpoint NAND size')
            controller.storage[:] = storage
            if 'nand_spare.bin' in z.namelist():
                spare = z.read('nand_spare.bin')
                if len(spare) != len(controller.spare):
                    raise ValueError('Invalid checkpoint NAND spare size')
                controller.spare[:] = spare
            for key, value in metadata['nand'].items():
                if key in ('commands', 'unsupported'):
                    value = Counter({int(k): v for k, v in value.items()})
                setattr(controller, key, value)
        if panel:
            for key, value in metadata['lcd'].items():
                if key in ('registers', 'sub_registers'):
                    value = {int(k): v for k, v in value.items()}
                elif key == 'counts':
                    value = Counter(value)
                elif key == 'events':
                    value = deque(value, maxlen=256)
                setattr(panel, key, value)
            if 'lcd_pixels.bin' in z.namelist():
                pixels = z.read('lcd_pixels.bin')
                if len(pixels) != len(panel.pixels):
                    raise ValueError('Invalid checkpoint GRAM length')
                panel.pixels[:] = pixels
            if 'lcd_sub_pixels.bin' in z.namelist():
                panel.sub_pixels[:] = z.read('lcd_sub_pixels.bin')
            elif panel.counts.get('writes', 0):
                panel.history_complete = False
        blob = z.read('cpu.bin')
        if len(blob) != uc.context_save().size:
            raise ValueError('CPU context size mismatch')
        context = UcContext.__new__(UcContext)
        context.__setstate__((blob, len(blob), UC_ARCH_ARM, UC_MODE_ARM))
        uc.context_restore(context)
        if timer:
            if 'timer' in metadata:
                for key, value in metadata['timer'].items():
                    setattr(timer, key, value)
            else:
                timer.initialize_after_restore()
        if mmc:
            if 'mmc' in metadata:
                if hasattr(mmc, 'restore'):
                    mmc.restore(metadata['mmc'])
                else:
                    for key, value in metadata['mmc'].items():
                        setattr(mmc, key, value)
            else:
                mmc.stopped = int.from_bytes(uc.mem_read(mmc.BASE, 4), 'little') == 1
        if mdsp:
            if 'mdsp_management' in metadata:
                for key, value in metadata['mdsp_management'].items():
                    if key in ('completed', 'unsupported'):
                        value = Counter({int(k): v for k, v in value.items()})
                    setattr(mdsp, key, value)
            else:
                mdsp.initialize_after_restore()
        if keypad and 'keypad' in metadata:
            for row, column in metadata['keypad']['pressed']:
                keypad.set_key(row, column, True)
            keypad.reads = metadata['keypad']['reads']
        return metadata
