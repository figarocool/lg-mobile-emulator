"""List the debug-message texts printed by code in an address range: msg_region.py CHECKPOINT LO HI"""
import json, struct, sys, zipfile
import numpy as np
z = zipfile.ZipFile(sys.argv[1]); meta = json.loads(z.read('metadata.json'))
lo, hi = int(sys.argv[2], 16), int(sys.argv[3], 16)
mem = {b: z.read(n) for b, e, _, n in meta['regions'] if b < 0x1a00000 and e - b >= 0x100000}
def read(a, n):
    for b, d in mem.items():
        if b <= a < b + len(d): return d[a - b:a - b + n]
    return b''
code = read(lo, hi - lo)
seen = {}
for i in range(0, len(code) - 2, 2):
    h = struct.unpack_from('<H', code, i)[0]
    if h & 0xf800 != 0x4800: continue
    reg = (h >> 8) & 7
    lit = ((lo + i + 4) & ~3) + (h & 0xff) * 4
    raw = read(lit, 4)
    if len(raw) < 4: continue
    base = struct.unpack('<I', raw)[0]
    for step in range(1, 5):
        if i + 2 * step + 2 > len(code): break
        h2 = struct.unpack_from('<H', code, i + 2 * step)[0]
        add = 0
        if h2 & 0xff00 == (0x3000 | reg << 8): add = h2 & 0xff
        elif h2 & 0xf800 == 0x1c00 and False: pass
        else: continue
        for st in (base + add, base):
            fmt = struct.unpack('<I', (read(st + 8, 4) or b'\0\0\0\0'))[0]
            text = read(fmt, 70).split(b'\0')[0]
            if 5 < len(text) and all(32 <= c < 127 for c in text):
                seen.setdefault(text.decode(), hex(lo + i)); break
for t, a in seen.items(): print(a, t)
