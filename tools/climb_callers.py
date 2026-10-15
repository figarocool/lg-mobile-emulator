"""Climb the static Thumb call chain upward from a function (heuristic: nearest preceding push {..lr})."""
import sys
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from find_callers import scan
from task_stack import load


def function_start(read, address):
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.skipdata = True
    for back in range(0x40, 0x1200, 0x40):
        start = address - back
        last = None
        for i in md.disasm(read(start, back), start):
            if i.mnemonic == 'push' and 'lr' in i.op_str:
                last = i.address
        if last is not None:
            return last
    return None


if __name__ == '__main__':
    path = sys.argv[1]
    read = load(path)
    level = [int(sys.argv[2], 16)]
    seen = set()
    for depth in range(int(sys.argv[3]) if len(sys.argv) > 3 else 4):
        callers = scan(path, set(level))
        nxt = []
        for site, target in callers:
            start = function_start(read, site)
            print('  ' * depth, hex(target), '<- call at', hex(site), 'in function', hex(start) if start else '?')
            if start and start not in seen:
                seen.add(start)
                nxt.append(start | 0)
        level = nxt
        if not level:
            break
