"""Inferred handset-state inputs: bit 2 of GPIO word 0x48000060 (polled at 0xeaddf6)
and bit 13 of 0x84000170 (returned by the helper at 0xeadcc2).

The firmware compares this bit with a stored byte and posts an event when it
changes. Treating it as the flip/slide sensor is a hypothesis; polarity is
selected on the command line and verified only by the firmware reaction.
"""
from unicorn import UC_HOOK_MEM_READ


class FlipSensor:
    LINES = ((0x48000060, 1 << 2), (0x84000170, 1 << 13))

    def __init__(self, uc, open_state):
        self.uc = uc
        self.open_state = open_state
        self.reads = 0
        for address, _ in self.LINES:
            uc.hook_add(UC_HOOK_MEM_READ, self.read, begin=address, end=address + 3)

    def read(self, uc, access, address, size, value, _):
        bit = dict(self.LINES)[address & ~3]
        word = int.from_bytes(uc.mem_read(address & ~3, 4), 'little')
        word = word | bit if self.open_state else word & ~bit
        uc.mem_write(address & ~3, word.to_bytes(4, 'little'))
        self.reads += 1

    def report(self):
        return {'kind': 'inferred flip sensor, bit 2 of 0x48000060 and bit 13 of 0x84000170', 'open': self.open_state,
                'reads': self.reads, 'verified': False}
