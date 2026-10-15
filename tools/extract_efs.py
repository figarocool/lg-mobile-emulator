"""Decode LG EFS2 OBTY/OBPT/OBDT records; does not construct raw NAND."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import struct

ROOT = Path(__file__).resolve().parents[1]

def parse(data):
    if not data.startswith(b'EFS2'):
        raise ValueError('Not an LG EFS2 container')
    offset = data.find(b'OBTY')
    if offset < 0:
        raise ValueError('No object records')
    objects = []

    def record(expected):
        nonlocal offset
        if offset + 8 > len(data) or data[offset:offset+4] != expected:
            raise ValueError(f'Expected {expected!r} at 0x{offset:x}')
        length = struct.unpack_from('<I', data, offset+4)[0]
        end = offset + 8 + length
        if end > len(data):
            raise ValueError('Truncated record')
        payload = data[offset+8:end]
        offset = end
        return payload

    while offset < len(data):
        start = offset
        kind = record(b'OBTY')
        if kind not in (b'\x00\x00\x00\x00', b'\x01\x00\x00\x00'):
            raise ValueError('Unknown object type')
        raw = record(b'OBPT')
        if not raw.endswith(b'\0') or b'\0' in raw[:-1]:
            raise ValueError('Invalid path string')
        name = raw[:-1].decode('ascii')
        path = PurePosixPath(name)
        if not path.is_absolute() or '..' in path.parts or len(path.parts) < 2:
            raise ValueError('Unsafe path')
        payload = record(b'OBDT') if kind[0] == 0 else None
        objects.append((name, payload, start))
    return objects

def extract(source, output):
    objects = parse(source.read_bytes())
    output.mkdir(parents=True, exist_ok=True)
    root = output.resolve()
    manifest = []
    for name, payload, offset in objects:
        target = root.joinpath(*PurePosixPath(name).parts[1:])
        if not target.resolve().is_relative_to(root):
            raise ValueError('Output symlink leaves extraction directory')
        if payload is None:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        manifest.append({'path': name, 'kind': 'directory' if payload is None else 'file',
                         'record_offset': hex(offset), 'size': len(payload) if payload is not None else 0,
                         'sha256': hashlib.sha256(payload).hexdigest() if payload is not None else None})
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest

if __name__ == '__main__':
    for source in sorted((ROOT / 'firmware').iterdir()):
        if source.read_bytes()[:4] == b'EFS2':
            category = 'MODULE' if 'MODULE' in source.name else 'MEDIA'
            manifest = extract(source, ROOT / 'extracted' / category)
            print(f'{category}: {sum(x["kind"] == "file" for x in manifest)} files, {len(manifest)} objects')
