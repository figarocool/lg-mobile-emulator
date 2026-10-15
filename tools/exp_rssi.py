import sys
from emulator import run, ROOT
off = int(sys.argv[1], 0); val = int(sys.argv[2], 0)
def setup(u, state):
    u.mem_write(0x19bcc68 + off, bytes([val]))
state = run('amss', True, 400000000, True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True, keypad=True,
            resume=ROOT/'analysis/net_camped.zip', debug_setup=setup, fast=True, uim_card=True, flip='open', imei='356938035643809', netsim=True, live_dir=__import__('pathlib').Path('/tmp/live_exp'))
import subprocess
print(state['stop'])
