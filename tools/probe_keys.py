"""Hold each matrix key from a checkpoint (flip open) and report how the main display reacts."""
import hashlib, json, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLAGS = ['--target', 'amss', '--nand', '--lcd-bus', '--shadow-mmio', '--register-banks', '--timer-irq',
         '--mmc-clock', '--block-trace', '--mdsp-management', '--keypad', '--flip', 'open', '--uim-card', '--fast']


def run(resume, limit, key):
    """Each run needs its own report: the report name is derived from flags, so isolate by a copy of the tree is overkill;
    instead the emulator is run serially per key and results are read back immediately."""
    args = [sys.executable, str(ROOT/'tools/emulator.py'), *FLAGS, '--resume', str(resume), '--limit', str(limit)]
    if key:
        args += ['--press', f'{key[0]},{key[1]}']
    subprocess.run(args, cwd=ROOT, capture_output=True, check=True)
    report = json.loads((ROOT/'analysis/amss_shadow_nand_lcd_banks_irq_mmc_blocks_mdsp_hle_keypad.json').read_text())
    lcd = report['lcd_bus']
    apdus = (report.get('uim_uart') or {}).get('apdus', [])
    verify = sum(1 for a in apdus if a[0].startswith('0020') and a[1])
    sub = (ROOT/'analysis/amss_lcd.ppm').read_bytes()  # main display with the flip open
    return {'key': key, 'frames': lcd['sub_frames'], 'pixels': lcd['sub_pixel_count'], 'main_pixels': lcd['pixel_writes'],
            'writes': lcd['counts']['writes'], 'hash': hashlib.md5(sub).hexdigest()[:8], 'verify': verify, 'sub': sub}


if __name__ == '__main__':
    resume, limit = Path(sys.argv[1]), int(sys.argv[2])
    out = ROOT/'analysis/keys_main'
    out.mkdir(exist_ok=True)
    results = []
    for key in [None] + [(r, c) for r in range(5) for c in range(7)]:
        r = run(resume, limit, key)
        name = 'base' if key is None else f'{key[0]}_{key[1]}'
        (out/f'{name}.ppm').write_bytes(r.pop('sub'))
        print(r, flush=True)
        results.append(r)
    (ROOT/'analysis/key_probe.json').write_text(json.dumps(results, indent=1))
