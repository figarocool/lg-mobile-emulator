"""Construct the optional factory country header in known synthetic NAND.

NV 9025 reads SSIKYU field 38. Original 0x70b32 loads its header from the
third reserved block; 0x715d2 checks magic/version/active and country +0x10.
This creates derived factory metadata, without patching the reader or CODE.
"""
import argparse
import json
import re
import struct
import zipfile
from pathlib import Path
from emulator import ROOT
from ssikyu_crypto import CryptoProbe


def build(resume, country):
    if not 0 <= country <= 0xffff:
        raise ValueError('Invalid country code')
    with zipfile.ZipFile(resume) as archive:
        metadata = json.loads(archive.read('metadata.json'))
        provenance = metadata.get('nand', {})
        if not provenance.get('synthetic') or not provenance.get('factory_fixture'):
            raise ValueError('Only a checkpoint with known synthetic factory metadata is accepted')
        block = None
        address = 0x022850c0
        for begin, end, permissions, name in metadata['regions']:
            if begin <= address <= end-3:
                block = struct.unpack_from('<I', archive.read(name), address-begin)[0]
                break
        if block is None or not 25 <= block < 31:
            raise ValueError('Unrecognized factory block allocation')
        nand = bytearray(archive.read('nand.bin'))
    offset = block * 32 * 512
    if nand[offset:offset+512] != b'\xff'*512:
        raise ValueError('Factory page already contains data; refusing to replace it')
    plain = bytearray(512)
    struct.pack_into('<IIIIH', plain, 0, 0xc7c3b7ba, 0xbdbab3c4, 1, 1, country)
    crypto = CryptoProbe()
    encrypted = crypto.transform(bytes(plain), encrypt=True)
    if crypto.transform(encrypted) != plain:
        raise ValueError('Original factory encryption round-trip failed')
    nand[offset:offset+512] = encrypted
    return nand, {'kind': 'synthetic optional factory country header', 'block': block,
                  'page': 0, 'value': country, 'source': 'original MEDIA Flex.ini',
                  'original_phone_nv_restored': False,
                  'native_read_and_reboot_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path, default=ROOT/'analysis/amss_modules_media_installed.zip')
    parser.add_argument('--output', type=Path, default=ROOT/'analysis/u310_resources_synthetic_nand.bin')
    args = parser.parse_args()
    text = (ROOT/'extracted/MEDIA/LGAPP/Media/Flex/Flex.ini').read_bytes()
    match = re.search(rb'^FLEX_COUNTRY_CODE=(\d+)\s*$', text, re.MULTILINE)
    if not match or not 0 <= int(match[1]) <= 0xffff:
        raise ValueError('Missing or invalid FLEX_COUNTRY_CODE')
    nand, report = build(args.resume, int(match[1]))
    args.output.write_bytes(nand)
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
