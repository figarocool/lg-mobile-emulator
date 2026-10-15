"""Locate Thumb code that loads a debug-message struct: ldr r0,[pc,#k] (base L) followed by adds/subs r0,#imm steps reaching the struct."""
import json, struct, sys, zipfile
z = zipfile.ZipFile(sys.argv[1]); meta = json.loads(z.read('metadata.json'))
targets = {int(a, 16) for a in sys.argv[2:]}
for b, e, _, n in meta['regions']:
    if b >= 0x1a00000 or e - b < 0x100000: continue
    d = z.read(n)
    for i in range(0, len(d) - 2, 2):
        h = struct.unpack_from('<H', d, i)[0]
        if h & 0xff00 != 0x4800: continue  # ldr r0,[pc,#imm*4]
        lit = ((b + i + 4) & ~3) + (h & 0xff) * 4 - b
        if lit + 4 > len(d): continue
        value = struct.unpack_from('<I', d, lit)[0]
        if not any(0 <= t - value < 0x800 or 0 <= value - t < 0x800 for t in targets): continue
        for j in range(1, 8):
            if i + 2 * j + 2 > len(d): break
            h2 = struct.unpack_from('<H', d, i + 2 * j)[0]
            if h2 & 0xff00 == 0x3000: value += h2 & 0xff
            elif h2 & 0xff00 == 0x3800: value -= h2 & 0xff
            elif h2 == 0x4780 or (h2 & 0xf800) == 0xf000 or (h2 & 0xff80) == 0x4780: break
            if value in targets:
                print(hex(b + i), hex(value)); break
