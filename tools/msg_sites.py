"""List the debug-message structs referenced from literal pools in a code range of a checkpoint."""
import struct, sys
from task_stack import load
r = load(sys.argv[1]); lo, hi = int(sys.argv[2], 16), int(sys.argv[3], 16)
def text(a):
    try:
        s = r(a, 80).split(b'\0')[0]
    except Exception:
        return None
    return s.decode() if len(s) > 4 and all(32 <= c < 127 for c in s) else None
d = r(lo, hi - lo)
for i in range(0, len(d) - 3, 4):
    w = struct.unpack_from('<I', d, i)[0]
    if not 0x1000000 < w < 0x1400000: continue
    for off in (0, 8, 0x34, 0x3c, 0x40, 0x48):
        try:
            f = struct.unpack('<I', r(w + off, 4))[0]
        except Exception: continue
        t = text(f)
        if t:
            print(hex(lo + i), hex(w + off), t); break
