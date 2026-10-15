"""Find code locations that print a given firmware debug message (literal-pool pointer to its struct array)."""
import json, struct, sys, zipfile
import numpy as np
z = zipfile.ZipFile(sys.argv[1]); meta = json.loads(z.read('metadata.json'))
needles = [s.encode() for s in sys.argv[2:]]
mem = {}
for b, e, _, n in meta['regions']:
    if b < 0x1a00000 and e - b >= 0x100000:
        mem[b] = z.read(n)
def words(base, data):
    return np.frombuffer(data[:len(data) // 4 * 4], dtype='<u4')
for needle in needles:
    strs = [b + m for b, d in mem.items() for m in [d.find(needle)] if m >= 0]
    for s in strs:
        for b, d in mem.items():
            w = words(b, d)
            for i in np.nonzero(w == s)[0]:
                struct_addr = b + int(i) * 4 - 8
                for b2, d2 in mem.items():
                    w2 = words(b2, d2)
                    hit = np.nonzero((w2 <= struct_addr) & (w2 > struct_addr - 0x800) & ((w2 & 3) == 0))[0]
                    refs = [hex(b2 + int(h) * 4) + ':' + hex(int(w2[h])) for h in hit[:6]]
                    if refs: print(needle.decode(), hex(struct_addr), refs)
