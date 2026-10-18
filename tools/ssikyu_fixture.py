"""Optional synthetic factory metadata; never used for a physical NAND dump."""
import struct
from ssikyu_crypto import CryptoProbe

MAGIC = [
    (0xbec6c0cc,0xbfa5c0cc), (0xbdc9b6f4,0xc4dab5e5),
    (0xbaf1c6bc,0xbeeeb5e5), (0xc6d1c6ae,0xc0cec6f7),
    (0xbfa5bebe,0xbebec4da), (0xc6dbbaed,0xb8afc5b0),
    (0xc5b0bdc3,0xc4f6bdba),
]

def initialize(controller, *, probe=None, block=27):
    if not controller.synthetic:
        raise ValueError('Synthetic SSIKYU metadata is only allowed on a synthetic NAND')
    if not 0 <= block < controller.SIZE // controller.BLOCK:
        raise ValueError('Invalid synthetic SSIKYU block')
    begin = block * controller.BLOCK
    length = len(MAGIC) * controller.PAGE
    if controller.storage[begin:begin+length] != b'\xff' * length:
        raise ValueError('SSIKYU candidate pages are not erased; refusing to replace them')
    probe = probe if probe is not None else CryptoProbe()
    encrypted = bytearray()
    for a, b in MAGIC:
        plain = bytearray(512)
        struct.pack_into('<III', plain, 0, a, b, 1)
        cipher = probe.transform(bytes(plain), encrypt=True)
        assert probe.transform(cipher) == plain
        encrypted.extend(cipher)
    controller.storage[begin:begin+length] = encrypted
    controller.factory_fixture = {
        'kind': 'synthetic empty SSIKYU metadata', 'block': block, 'pages': len(MAGIC),
        'source': 'factory fallback templates and original page encryption routine',
        'original_phone_nv_data_recovered': False,
    }
    return controller.factory_fixture


def initialize_country(controller, country, *, probe, block):
    """Optional factory country header, only in explicitly synthetic NAND."""
    if not controller.synthetic or not 0 <= country <= 0xffff:
        raise ValueError('Country fixture requires synthetic NAND and a 16-bit country')
    if not 0 <= block < controller.SIZE // controller.BLOCK:
        raise ValueError('Country block outside synthetic NAND')
    offset = block * controller.BLOCK
    if controller.storage[offset:offset+512] != b'\xff'*512:
        raise ValueError('Country page is not erased')
    plain = bytearray(512)
    struct.pack_into('<IIIIH', plain, 0, 0xc7c3b7ba, 0xbdbab3c4, 1, 1, country)
    encrypted = probe.transform(bytes(plain), encrypt=True)
    if probe.transform(encrypted) != plain:
        raise ValueError('Country fixture encryption roundtrip failed')
    controller.storage[offset:offset+512] = encrypted
    return dict(kind='synthetic factory country header', block=block,
                source='original MEDIA Flex.ini', country=country,
                original_phone_nv_restored=False)
