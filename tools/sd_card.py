"""microSD card images: create, format, copy files in/out. A card is a plain FAT image file the phone sees as its card.

mkfs.fat / mtools are used when installed; otherwise a built-in FAT16 formatter handles cards up to 2 GB.
"""
import re
import shutil
import struct
import subprocess
from pathlib import Path

SECTOR = 512
MAX_BUILTIN_MB = 2047


def run(*args):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True)


PARTITION_START = 2048            # sectors (1 MiB), the usual alignment of a real card
FAT_TYPES = (0x04, 0x06, 0x0b, 0x0c, 0x0e)


def partition_offset(path):
    """Byte offset of the FAT volume: first partition of the MBR, or 0 for a card formatted without partition table."""
    with open(path, 'rb') as handle:
        sector = handle.read(SECTOR)
    if sector[510:512] != b'\x55\xaa':
        return 0
    if sector[54:57] == b'FAT' or sector[82:85] == b'FAT':
        return 0
    entry = sector[446:462]
    if entry[4] in FAT_TYPES:
        return struct.unpack_from('<I', entry, 8)[0] * SECTOR
    return 0


def ref(path):
    """mtools image reference ('file@@offset' when the volume sits inside a partition)."""
    offset = partition_offset(path)
    return f'{path}@@{offset}' if offset else str(path)


def write_mbr(path, start, sectors):
    mbr = bytearray(SECTOR)
    mbr[446:462] = struct.pack('<B3sB3sII', 0x00, b'\x20\x21\x00', 0x0e if sectors >= 0x10000 else 0x06, b'\xfe\xff\xff', start, sectors)
    mbr[510:512] = b'\x55\xaa'
    with open(path, 'r+b') as handle:
        handle.write(mbr)


def clean_label(label):
    return re.sub(r'[^A-Z0-9 _-]', '', (label or 'U310SD').upper())[:11].ljust(11)


def builtin_fat16(size_bytes, label, hidden=0):
    """Boot sector, two FATs and an empty root directory of a FAT16 volume, as one bytes object per region."""
    total = size_bytes // SECTOR
    if total >= 0x10000 * 32:
        raise ValueError('Il formattatore interno arriva a 2 GB: installa dosfstools per schede più grandi')
    spc = 2
    for candidate, limit in ((2, 32680), (4, 262144), (8, 524288), (16, 1048576), (32, 2097152), (64, 4194304)):
        spc = candidate
        if total <= limit:
            break
    reserved, root_entries, fats = 1, 512, 2
    root_sectors = root_entries * 32 // SECTOR
    fat_sectors = 1
    while True:
        data = total - reserved - fats * fat_sectors - root_sectors
        clusters = data // spc
        needed = ((clusters + 2) * 2 + SECTOR - 1) // SECTOR
        if needed <= fat_sectors:
            break
        fat_sectors = needed
    boot = bytearray(SECTOR)
    boot[0:3] = b'\xeb\x3c\x90'
    boot[3:11] = b'U310EMU '
    struct.pack_into('<HBHBHHBHHHII', boot, 11, SECTOR, spc, reserved, fats, root_entries,
                     total if total < 0x10000 else 0, 0xf8, fat_sectors, 63, 255, hidden, total if total >= 0x10000 else 0)
    boot[36] = 0x80
    boot[38] = 0x29
    struct.pack_into('<I', boot, 39, 0x55310A5D)
    boot[43:54] = label.encode('ascii')
    boot[54:62] = b'FAT16   '
    boot[510:512] = b'\x55\xaa'
    fat = bytearray(fat_sectors * SECTOR)
    fat[0:4] = b'\xf8\xff\xff\xff'
    return bytes(boot), bytes(fat), root_sectors * SECTOR, reserved, fat_sectors


def create_image(path, size_mb, label='U310SD'):
    """Create a new blank card image (sparse file) and format it."""
    path = Path(path)
    if size_mb < 8 or size_mb > 32768:
        raise ValueError('Dimensione scheda: da 8 MB a 32768 MB')
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as handle:
        handle.truncate(size_mb * 1024 * 1024)
    try:
        format_image(path, label)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def format_image(path, label='U310SD'):
    """Erase the card and create a partition table with one FAT volume (like a real card)."""
    path = Path(path)
    size = path.stat().st_size
    name = clean_label(label)
    start = PARTITION_START
    sectors = size // SECTOR - start
    with open(path, 'r+b') as handle:           # wipe the first MB so old metadata disappears
        handle.write(bytes(min(size, 1 << 20) if size > (1 << 20) else size))
    if shutil.which('mkfs.fat'):
        fat_bits = '16' if size <= 2047 * 1024 * 1024 else '32'
        result = run('mkfs.fat', '-F', fat_bits, '-n', name.strip() or 'U310SD', '--offset', start, path, sectors // 2)
        if result.returncode != 0:
            raise ValueError('Formattazione non riuscita: ' + result.stderr.strip()[:200])
    else:
        if size > MAX_BUILTIN_MB * 1024 * 1024:
            raise ValueError('Per schede oltre 2 GB serve dosfstools (mkfs.fat)')
        boot, fat, root_bytes, reserved, fat_sectors = builtin_fat16(sectors * SECTOR, name, hidden=start)
        with open(path, 'r+b') as handle:
            handle.seek(start * SECTOR)
            handle.write(boot)
            handle.seek((start + reserved) * SECTOR)
            handle.write(fat)
            handle.write(fat)
            handle.write(bytes(root_bytes))
    write_mbr(path, start, sectors)


def info(path):
    """{'size_mb', 'label', 'fs', 'used_mb'} or raises ValueError when the file is not a FAT image."""
    path = Path(path)
    with open(path, 'rb') as handle:
        handle.seek(partition_offset(path))
        boot = handle.read(SECTOR)
    if boot[510:512] != b'\x55\xaa':
        raise ValueError('Il file non contiene un file system FAT')
    fs = boot[54:62].decode('ascii', 'replace').strip() or boot[82:90].decode('ascii', 'replace').strip()
    label = boot[43:54].decode('ascii', 'replace').strip()
    return {'size_mb': path.stat().st_size // (1024 * 1024), 'label': label, 'fs': fs}


def copy_in(path, sources, destination=''):
    """Copy files/folders from the PC into the card (needs mtools)."""
    if not shutil.which('mcopy'):
        raise ValueError('Per copiare file serve mtools (mcopy)')
    for source in sources:
        result = run('mcopy', '-i', ref(path), '-s', '-o', source, f'::{destination}')
        if result.returncode != 0:
            raise ValueError(f'Copia non riuscita: {result.stderr.strip()[:200]}')


def copy_out(path, destination):
    """Copy the whole card content out to a PC folder."""
    if not shutil.which('mcopy'):
        raise ValueError('Per estrarre i file serve mtools (mcopy)')
    Path(destination).mkdir(parents=True, exist_ok=True)
    result = run('mcopy', '-i', ref(path), '-s', '-o', '::', destination)
    if result.returncode != 0:
        raise ValueError(f'Estrazione non riuscita: {result.stderr.strip()[:200]}')


def listing(path):
    if not shutil.which('mdir'):
        return ''
    return run('mdir', '-i', ref(path), '-/', '::').stdout


# ---- file-level operations (mtools) -------------------------------------------------------------------------
LINE = re.compile(r'^(?P<short>\S+(?: \S+)?)\s+(?P<ext>\S*)?\s+(?P<size><DIR>|\d+)\s+(?P<date>\d{4}-\d\d-\d\d)\s+(?P<time>\d+:\d\d)(?:\s+(?P<long>.+))?$')


def _need_mtools():
    if not shutil.which('mdir'):
        raise ValueError('Per gestire i file della scheda serve mtools')


def _target(folder, name=''):
    folder = '/' + folder.strip('/') if folder.strip('/') else ''
    return f'::{folder}/{name}' if name else f'::{folder or "/"}'


def entries(path, folder=''):
    """[(name, is_dir, size)] of one folder of the card, folders first."""
    _need_mtools()
    result = run('mdir', '-i', ref(path), '-a', _target(folder))
    if result.returncode != 0:
        raise ValueError('Cartella non leggibile: ' + result.stderr.strip()[:200])
    found = []
    for raw in result.stdout.splitlines():
        match = LINE.match(raw.rstrip())
        if not match or match['short'] in ('.', '..'):
            continue
        name = match['long'] or (match['short'] + ('.' + match['ext'] if match['ext'] else ''))
        is_dir = match['size'] == '<DIR>'
        if name in ('.', '..'):
            continue
        found.append((name, is_dir, 0 if is_dir else int(match['size'])))
    return sorted(found, key=lambda e: (not e[1], e[0].lower()))


def make_folder(path, folder, name):
    _need_mtools()
    result = run('mmd', '-i', ref(path), _target(folder, name))
    if result.returncode != 0:
        raise ValueError('Cartella non creata: ' + result.stderr.strip()[:200])


def delete(path, folder, name, is_dir):
    _need_mtools()
    result = run('mdeltree' if is_dir else 'mdel', '-i', ref(path), _target(folder, name))
    if result.returncode != 0:
        raise ValueError('Eliminazione non riuscita: ' + result.stderr.strip()[:200])


def rename(path, folder, old, new):
    _need_mtools()
    result = run('mren', '-i', ref(path), _target(folder, old), _target(folder, new))
    if result.returncode != 0:
        raise ValueError('Rinomina non riuscita: ' + result.stderr.strip()[:200])


def upload(path, sources, folder=''):
    copy_in(path, sources, folder.strip('/') and '/' + folder.strip('/'))


def download(path, folder, name, destination):
    _need_mtools()
    Path(destination).mkdir(parents=True, exist_ok=True)
    result = run('mcopy', '-i', ref(path), '-s', '-o', _target(folder, name), destination)
    if result.returncode != 0:
        raise ValueError('Download non riuscito: ' + result.stderr.strip()[:200])


def free_space(path):
    """Free bytes on the card (from mdir's summary), or None."""
    if not shutil.which('mdir'):
        return None
    out = run('mdir', '-i', ref(path), '::/').stdout
    match = re.search(r'([\d ]+) bytes free', out)
    return int(match[1].replace(' ', '')) if match else None


def reformat(path, size_mb, label='U310SD'):
    """Change the card size and format it again: the old content is lost."""
    path = Path(path)
    if size_mb < 8 or size_mb > 32768:
        raise ValueError('Dimensione scheda: da 8 MB a 32768 MB')
    with open(path, 'r+b') as handle:
        handle.truncate(size_mb * 1024 * 1024)
    format_image(path, label)
