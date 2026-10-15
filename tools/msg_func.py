"""Find the code that prints a debug message and dump the function around it: msg_func.py CHECKPOINT "text" [bytes]"""
import json, re, subprocess, sys, zipfile
import numpy as np
z = zipfile.ZipFile(sys.argv[1]); meta = json.loads(z.read('metadata.json'))
mem = {b: z.read(n) for b, e, _, n in meta['regions'] if b < 0x1a00000 and e - b >= 0x100000}
needle = sys.argv[2].encode(); span = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x80
structs = []
for b, d in mem.items():
    for m in re.finditer(re.escape(needle), d):
        s = b + m.start()
        for b2, d2 in mem.items():
            w2 = np.frombuffer(d2[:len(d2) // 4 * 4], dtype='<u4')
            for i in np.nonzero(w2 == s)[0]:
                structs.append(hex(b2 + int(i) * 4 - 8))
out = subprocess.run([sys.executable, str(__import__('pathlib').Path(__file__).parent / 'msg_users.py'), sys.argv[1]] + structs, capture_output=True, text=True).stdout
print(out)
for line in out.splitlines():
    code = int(line.split()[0], 16)
    print(subprocess.run([sys.executable, str(__import__('pathlib').Path(__file__).parent / 'disas.py'), sys.argv[1], hex(code - span), hex(span + 0x20)], capture_output=True, text=True).stdout)
