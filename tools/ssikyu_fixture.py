"""Optional synthetic factory metadata; never used for a physical NAND dump."""
import struct
from ssikyu_crypto import CryptoProbe

MAGIC = [
    (0xbec6c0cc,0xbfa5c0cc), (0xbdc9b6f4,0xc4dab5e5),
    (0xbaf1c6bc,0xbeeeb5e5), (0xc6d1c6ae,0xc0cec6f7),
    (0xbfa5bebe,0xbebec4da), (0xc6dbbaed,0xb8afc5b0),
    (0xc5b0bdc3,0xc4f6bdba),
]

def initialize(controller):
    if not controller.synthetic:
        raise ValueError('Synthetic SSIKYU metadata is only allowed on a synthetic NAND')
    begin = 27 * controller.BLOCK
    length = len(MAGIC) * controller.PAGE
    if controller.storage[begin:begin+length] != b'\xff' * length:
        raise ValueError('SSIKYU candidate pages are not erased; refusing to replace them')
    probe = CryptoProbe()
    encrypted = bytearray()
    for a, b in MAGIC:
        plain = bytearray(512)
        struct.pack_into('<III', plain, 0, a, b, 1)
        cipher = probe.transform(bytes(plain), encrypt=True)
        assert probe.transform(cipher) == plain
        encrypted.extend(cipher)
    controller.storage[begin:begin+length] = encrypted
    controller.factory_fixture = {
        'kind': 'synthetic empty SSIKYU metadata', 'block': 27, 'pages': len(MAGIC),
        'source': 'factory fallback templates and original page encryption routine',
        'original_phone_nv_data_recovered': False,
    }
    return controller.factory_fixture
