"""Runtime CODE decoder; the user supplies their own 16-byte local key."""
from pathlib import Path
import struct
from Crypto.Cipher import AES
PREFIX=0xa00
BLOCK=0x4000
LOAD=0xc0000
DEFAULT_KEY=Path(__file__).resolve().parents[1]/'data/u880/code-key.bin'

def decrypt(data, key):
    if len(key) != 16:
        raise ValueError('AES key must be exactly 16 bytes')
    if len(data) < PREFIX+32 or len(data) % 16:
        raise ValueError('CODE must be a nontruncated multiple of 16 bytes')
    return b''.join(AES.new(key, AES.MODE_CBC, iv=bytes(16)).decrypt(data[i:i+BLOCK])
                    for i in range(0, len(data), BLOCK))


def validate_vectors(plain):
    if len(plain) < PREFIX+32:
        raise ValueError('Missing ARM vectors')
    vectors = []
    names = ('reset', 'undefined', 'swi', 'prefetch_abort', 'data_abort', 'reserved', 'irq', 'fiq')
    end = LOAD+len(plain)-PREFIX
    for index, (word, name) in enumerate(zip(struct.unpack_from('<8I', plain, PREFIX), names)):
        if word >> 24 != 0xEA:
            raise ValueError(f'Wrong key/format: vector {index} is not an ARM unconditional branch')
        displacement = word & 0xFFFFFF
        if displacement & 0x800000:
            displacement -= 0x1000000
        target = LOAD+index*4+8+displacement*4
        if not LOAD <= target < end:
            raise ValueError(f'Vector {index} leaves the decoded ARM image')
        vectors.append({'name': name, 'address': hex(LOAD+index*4), 'target': hex(target)})
    return vectors
