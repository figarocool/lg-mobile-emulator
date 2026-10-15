"""Run a scripted key sequence from a checkpoint and save the resulting checkpoint and screens.

Sequence items: ROW,COL[:HOLD] presses a matrix key, '-' releases everything, each followed by a
run of HOLD instructions (default 8M for a press, 10M for a release). Example:
  python3 tools/press_keys.py analysis/pin_prompt.zip analysis/pin_typed.zip 4,1 - 4,1 - 4,1 - 4,1 -
"""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLAGS = ['--target', 'amss', '--nand', '--lcd-bus', '--shadow-mmio', '--register-banks', '--timer-irq',
         '--mmc-clock', '--block-trace', '--mdsp-management', '--keypad', '--flip', 'open', '--uim-card', '--fast']


def step(resume, output, key, instructions):
    args = [sys.executable, str(ROOT / 'tools/emulator.py'), *FLAGS, '--resume', str(resume),
            '--save-checkpoint', str(output), '--limit', str(instructions)]
    args += ['--press', key] if key else ['--release-keys']
    subprocess.run(args, cwd=ROOT, capture_output=True, check=True)


def main():
    resume, final = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    work = ROOT / 'analysis/press_tmp'
    work.mkdir(exist_ok=True)
    current = resume
    for index, item in enumerate(sys.argv[3:]):
        key, _, hold = item.partition(':')
        key = None if key == '-' else key
        instructions = int(float(hold.rstrip('M')) * 1e6) if hold else (8_000_000 if key else 10_000_000)
        output = final if index == len(sys.argv) - 4 else work / f'step{index}.zip'
        step(current, output, key, instructions)
        current = output
    print('done', final)


if __name__ == '__main__':
    main()
