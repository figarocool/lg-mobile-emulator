import sys
from emulator import run, ROOT
from guest_call import call
cands = {
 'mcc222 n2 mnc99f': bytes([2,2,2,2,9,9,0xf]),
 'mcc222 n2 mnc990': bytes([2,2,2,2,9,9,0]),
 'seen': bytes([2,2,9,2,9,9,0xf]),
 'seen2': bytes([2,9,2,9,9,0xf,0]),
}
def setup(u, state):
    for name, b in cands.items():
        u.mem_write(0x04f00300, b + b'\0')
        d0 = int.from_bytes(b[0:4], 'little'); d1 = int.from_bytes((b + b'\0')[4:8], 'little')
        r = call(u, 0x113a104, (d0, d1), thumb=False)
        print(name, b.hex(), '->', hex(r))
    state['stop'] = 'experiment done'; u.emu_stop()
run('amss', True, 1000, True, lcd=True, banks=True, irq=True, mmc=True, mdsp_management=True, keypad=True,
    resume=ROOT/'analysis/net_imei.zip', debug_setup=setup, fast=True, uim_card=True, flip='open', imei='356938035643809')
