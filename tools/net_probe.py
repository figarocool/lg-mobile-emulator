"""Force ONLINE in a checkpoint copy with the simulated network and print the firmware's reaction."""
import sys
from unicorn.arm_const import *
from emulator import run, ROOT
limit = int(float(sys.argv[1])); skip = sys.argv[2] if len(sys.argv) > 2 else ''
def setup(u, state):
    state['netsim'].go_online()
state = run('amss', True, limit, True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True, keypad=True,
            resume=ROOT / 'analysis/net_imei.zip', debug_setup=setup, fast=True, uim_card=True, flip='open',
            imei='356938035643809', rf_defaults=True, netsim=True)
import json
print(json.dumps(state['netsim']['log'], indent=0)[:6000])
print(state['stop'], state['instructions'])
