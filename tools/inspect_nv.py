"""Decode LG NV2 and compare NV records without printing phone identifiers."""
from pathlib import Path
from collections import Counter
import struct
import json
import hashlib

ROOT = Path(__file__).resolve().parents[1]
KEY = (0,9,11,3,7,12,1,10,4,13,14,8,15,5,2,6)
RECORD_SIZE = 133

def decode_nv2(data):
    if data[:4] != b'RGNV':
        raise ValueError('Unknown NV2 signature')
    plain = bytes(((byte-KEY[i%16]) & 255) ^ KEY[i%16] for i, byte in enumerate(data[4:]))
    if len(plain) < 32:
        raise ValueError('Truncated NV2 header')
    version = struct.unpack_from('<I', plain)[0]
    count = struct.unpack_from('<I', plain, 12)[0]
    if version != 2 or len(plain) != 32 + count*RECORD_SIZE:
        raise ValueError('Unsupported NV2 version or record count mismatch')
    # Preserve the original 32-byte header for reversible round-trip verification.
    encoded = b'RGNV' + bytes(((byte ^ KEY[i%16])+KEY[i%16]) & 255 for i, byte in enumerate(plain))
    if encoded != data:
        raise ValueError('NV2 round-trip mismatch')
    model = plain[4:8].decode('ascii')
    return {'version': version, 'model': model, 'count': count,
            'systemtime': list(struct.unpack_from('<8H', plain, 16))}, plain[32:]

def parse_records(data):
    if not data or len(data) % RECORD_SIZE:
        raise ValueError('NV data must be a sequence of 133-byte records')
    records = {}
    for offset in range(0, len(data), RECORD_SIZE):
        flag, item = struct.unpack_from('<BH', data, offset)
        payload = data[offset+3:offset+131]
        status = struct.unpack_from('<H', data, offset+131)[0]
        if flag != 1:
            raise ValueError('Unexpected record flag')
        records.setdefault(item, []).append({'payload': payload, 'status': status})
    return records

def summarize(path, data, records):
    return {'file': path.name, 'sha256': hashlib.sha256(data).hexdigest(),
            'records': sum(len(group) for group in records.values()), 'unique_items': len(records),
            'item_ids': sorted(records), 'duplicate_item_counts': {i:len(g) for i,g in records.items() if len(g)>1},
            'statuses': dict(Counter(r['status'] for group in records.values() for r in group))}

if __name__ == '__main__':
    u310 = ROOT/'firmware/u310.nvm'
    donor = ROOT/'references/NV_U880_U890.nv2'
    a = u310.read_bytes()
    b = donor.read_bytes()
    header, decoded = decode_nv2(b)
    first, second = parse_records(a), parse_records(decoded)
    common = first.keys() & second.keys()
    def payloads(records, item):
        return sorted(r['payload'] for r in records[item])
    result = {'u310': summarize(u310, a, first), 'donor': summarize(donor, b, second),
              'donor_header': header, 'common_items': len(common),
              'same_payload_ids': sorted(i for i in common if payloads(first,i)==payloads(second,i)),
              'different_payload_ids': sorted(i for i in common if payloads(first,i)!=payloads(second,i)),
              'u310_only_ids': sorted(first.keys()-second.keys()),
              'donor_only_ids': sorted(second.keys()-first.keys()),
              'notes': ['NV2 arithmetic transform inferred from repeated zero padding and header validation',
                        '133-byte layout: flag, uint16 item, 128 payload bytes, uint16 status',
                        'NV item values are not printed or included in this JSON',
                        'Duplicate IDs are preserved as separate records; may represent multiple NAM/index values',
                        'Donor values are not installed into the emulator',
                        'NV backups are logical item records, not raw SSIKYU NAND headers']}
    (ROOT/'references/NV_U880_U890.decoded.nvm').write_bytes(decoded)
    (ROOT/'analysis/nv_comparison.json').write_text(json.dumps(result, indent=2)+'\n')
    print(f'U310: {len(first)} items; donor {header["model"]}: {header["count"]} records / {len(second)} items; common: {len(common)}')
    print(f'Identical payloads: {len(result["same_payload_ids"])}; different: {len(result["different_payload_ids"])}')
