"""Static scan of a checkpoint's code for Thumb BL/BLX and ARM BL/BLX callers of a target address."""
import json, struct, sys, zipfile


def thumb_targets(data, base):
    for i in range(0, len(data) - 3, 2):
        h1, h2 = struct.unpack_from('<HH', data, i)
        if h1 & 0xf800 == 0xf000 and h2 & 0xc000 == 0xc000 and h2 & 0x1000 or h1 & 0xf800 == 0xf000 and h2 & 0xd000 == 0xc000:
            off = ((h1 & 0x7ff) << 11) | (h2 & 0x7ff)
            if off & 0x200000:
                off -= 0x400000
            target = base + i + 4 + (off << 1)
            if h2 & 0x1000 == 0:  # BLX to ARM
                target &= ~3
            yield base + i, target


def scan(path, wanted, limit=0x1a00000):
    z = zipfile.ZipFile(path)
    meta = json.loads(z.read('metadata.json'))
    found = []
    for begin, end, _, name in meta['regions']:
        if begin >= limit or end - begin < 0x100000:
            continue
        data = z.read(name)[:limit - begin]
        for site, target in thumb_targets(data, begin):
            if target in wanted:
                found.append((site, target))
    return found


if __name__ == '__main__':
    wanted = {int(x, 16) for x in sys.argv[2:]}
    for site, target in scan(sys.argv[1], wanted):
        print(hex(site), '->', hex(target))
