"""Print candidate return addresses on a saved REX task stack (read-only, from a checkpoint)."""
import json, struct, sys, zipfile


def load(path):
    z = zipfile.ZipFile(path)
    meta = json.loads(z.read('metadata.json'))
    cache = {}

    def read(address, size):
        for begin, end, _, name in meta['regions']:
            if begin <= address and address + size - 1 <= end:
                data = cache.setdefault(name, z.read(name))
                return data[address-begin:address-begin+size]
        raise KeyError(hex(address))
    return read


def tasks(read):
    address = 0x019a4104
    while 0x01800000 <= address < 0x03400000:
        data = read(address, 0x80)
        name = data[0x60:0x6c].split(b'\0')[0].decode('ascii', 'replace')
        if not name:
            break
        yield name, address, struct.unpack_from('<I', data)[0], struct.unpack_from('<I', data, 0x28)[0]
        address = struct.unpack_from('<I', data, 0x28)[0]


if __name__ == '__main__':
    read = load(sys.argv[1])
    wanted = sys.argv[2:]
    for name, address, sp, _ in tasks(read):
        if name.strip() in wanted:
            print(name, hex(address), 'sp', hex(sp))
            words = struct.unpack('<48I', read(sp, 192))
            print(' '.join(hex(w) for w in words))
