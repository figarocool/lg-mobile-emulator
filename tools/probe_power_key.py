"""Hold each key from a checkpoint just before the self shutdown and report which ones avoid it.
A shutdown is recognised by the TMC 'Stop task' messages (needs U310_MSG_WATCH)."""
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLAGS = ['--target', 'amss', '--nand', '--lcd-bus', '--shadow-mmio', '--register-banks', '--timer-irq',
         '--mmc-clock', '--mdsp-management', '--keypad', '--flip', 'open', '--uim-card', '--fast']
REPORT = ROOT / 'analysis/amss_shadow_nand_lcd_banks_irq_mmc_mdsp_hle_keypad.json'


def run(resume, key, limit):
    args = [sys.executable, str(ROOT / 'tools/emulator.py'), *FLAGS, '--resume', str(resume), '--limit', str(limit)]
    if key:
        args += ['--press', f'{key[0]},{key[1]}']
    env = dict(os.environ, U310_MSG_WATCH='30000')
    subprocess.run(args, cwd=ROOT, capture_output=True, check=True, env=env)
    msgs = json.loads(REPORT.read_text()).get('msg_watch') or []
    return sum(1 for m in msgs if m[1].startswith('=TMC= Stop task')), len(msgs)


if __name__ == '__main__':
    resume, limit = Path(sys.argv[1]).resolve(), int(sys.argv[2])
    results = {}
    for key in [None] + [(r, c) for r in range(5) for c in range(7)]:
        stops, total = run(resume, key, limit)
        results[str(key)] = stops
        print(key, 'stop-task messages:', stops, flush=True)
    (ROOT / 'analysis/power_key_probe.json').write_text(json.dumps(results, indent=1))
