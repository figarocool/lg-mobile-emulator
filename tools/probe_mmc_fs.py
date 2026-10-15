"""Ask the original file-system API whether mmc1 and a file on the card exist (debugger call in a checkpoint copy)."""
import sys
from emulator import run, ROOT
from native_fs_calls import NativeFsCalls
paths = sys.argv[2:] or ['mmc1', 'mmc1/hello.txt', 'LGAPP/Pxo/PhoneMngr.pxo']
results = []
def requests():
    for path in paths:
        for kind in (1, 0):
            r = yield {'operation': 'test', 'path': path, 'kind': kind}
            results.append((path, kind, r))
session = NativeFsCalls(requests())
state = run('amss', True, 50000000, True, lcd=True, banks=True, irq=True, mmc=True, block_trace=True, mdsp_management=True,
            keypad=True, resume=ROOT / sys.argv[1], debug_setup=session.setup, debug_finish=session.finish, uim_card=True, imei='356938035643809')
for r in results: print(r)
print(state['stop'])
m=state.get('mmc_clock'); print(m and {'reads':m.get('reads'),'writes':m.get('writes'),'groups':[g for g in m.get('groups',[])][:30]})
