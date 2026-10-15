"""Reproducible inventory and entropy map, without altering firmware."""
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
result = []
for path in sorted((ROOT / 'firmware').iterdir()):
    data = path.read_bytes()
    item = {'name': path.name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'header': data[:64].hex(), 'entropy_16k': [], 'identification_strings': []}
    if path.suffix.lower() == '.bin':
        for offset in range(0, len(data), 16384):
            block = data[offset:offset + 16384]
            n = len(block)
            entropy = -sum(count/n * math.log2(count/n) for count in Counter(block).values())
            item['entropy_16k'].append([hex(offset), round(entropy, 3)])
        for match in re.finditer(rb'[ -~]{8,}', data):
            if re.search(rb'QUALCOMM|MSM6250|U310-|JNAND|AMSS|ZREX|<c-os>|Update error|nand_device', match[0]):
                item['identification_strings'].append({'offset': hex(match.start()),
                    'text': match[0][:240].decode('ascii')})
    result.append(item)
output = ROOT / 'analysis/firmware_inventory.json'
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(result, indent=2) + '\n')
print(output)
