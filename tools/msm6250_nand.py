"""NAND controller subset inferred from U310 firmware (not a complete SoC).

Register/command evidence is recorded in analysis/NAND.md. Completion is
instantaneous; IRQ delivery, ECC and controller timing are not implemented.
"""
from collections import Counter
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_READ

class NandController:
    BASE = 0x64000000
    IRQ = 0x84000244
    ACK = 0x8400024c
    SIZE = 64 * 1024 * 1024
    PAGE = 512
    BLOCK = 32 * PAGE
    DIRECT = 0x28000000

    def __init__(self, image=None):
        if image is not None and len(image) != self.SIZE:
            raise ValueError('NAND image must be a raw 64 MiB dump; CODE/EFS containers are not raw NAND')
        self.storage = bytearray(image) if image is not None else bytearray(b'\xff') * self.SIZE
        self.spare = bytearray(b'\xff') * (self.SIZE // self.PAGE * 16)
        self.synthetic = image is None
        self.address = 0
        self.config = 0
        self.status = 0
        self.pending = 0
        self.commands = Counter()
        self.unsupported = Counter()
        self.spare_word = 0xffffffff
        self.direct_command = 0
        self.direct_status_reads = 0
        self.factory_fixture = None

    def attach(self, uc):
        uc.mem_map(self.BASE, 0x1000)
        uc.mem_map(0x84000000, 0x1000)
        uc.mem_map(self.DIRECT, 0x1000)
        uc.mem_write(self.BASE, b'\xff' * (self.PAGE + 16))
        uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self._memory,
                    begin=self.BASE, end=self.BASE + 0xfff)
        uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self._memory,
                    begin=self.IRQ, end=self.ACK + 3)
        uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self._memory,
                    begin=self.DIRECT, end=self.DIRECT+3)

    def _memory(self, uc, access, address, size, value, _):
        if address == self.DIRECT:
            if access == UC_MEM_READ:
                if self.direct_command in (0x70, 0x74):
                    # 0x358a1c checks the low two bits after issuing 0x74;
                    # success here assumes no physical ECC faults.
                    result = 0xc0 | (1 if self.status & 0x88 else 0)
                else:
                    result = 0xff
                self.direct_status_reads += 1
                uc.mem_write(address, result.to_bytes(4, 'little')[:size])
            else:
                self.direct_command = value & 0xff
            return
        if access == UC_MEM_READ:
            values = {self.IRQ: self.pending, self.BASE + 0x308: self.status,
                      self.BASE + 0x304: self.address, self.BASE + 0x31c: self.config,
                      self.BASE + 0x320: self.spare_word}
            if address in values:
                uc.mem_write(address, values[address].to_bytes(4, 'little')[:size])
            return
        if address == self.ACK:
            self.pending &= ~value  # Firmware clears mask 6 before each operation.
        elif address == self.BASE + 0x304:
            self.address = value
        elif address == self.BASE + 0x31c:
            self.config = value
        elif address == self.BASE + 0x300:
            self.execute(uc, value)

    def execute(self, uc, command):
        self.commands[command] += 1
        if command not in (5, 6):
            self.status = 0
        if command == 7:
            # Firmware extracts manufacturer=(status>>23)&255, device=(status>>15)&255.
            self.status = (0x98 << 23) | (0x76 << 15)
        elif command in (5, 6):
            # The discovery routine reads the ID result after both status operations.
            pass
        elif command == 2:
            # 0x02202c90 sets page address + 5 and reads bad-block marker at +0x320.
            # No physical OOB dump available: initial chip has no bad blocks.
            if self.address >= self.SIZE:
                self.status = 0x88
                self.spare_word = 0xffffffff
            else:
                start = self.address // self.PAGE * 16
                index = self.address % self.PAGE
                payload = self.spare[start+index:start+min(index+4, 16)] if index < 16 else b''
                self.spare_word = int.from_bytes(payload.ljust(4, b'\xff'), 'little')
        elif command == 0:
            pass
        elif command in (1, 3, 4):
            offset = self.address
            if offset + self.PAGE > self.SIZE or offset % self.PAGE:
                self.status = 0x88
            elif command == 1:
                spare_offset = offset // self.PAGE * 16
                uc.mem_write(self.BASE, bytes(self.storage[offset:offset+self.PAGE]) +
                             bytes(self.spare[spare_offset:spare_offset+16]))
            elif command == 3:
                incoming = bytes(uc.mem_read(self.BASE, self.PAGE))
                for i, byte in enumerate(incoming):
                    self.storage[offset+i] &= byte  # NAND can program only 1 -> 0.
                spare_offset = offset // self.PAGE * 16
                for i, byte in enumerate(bytes(uc.mem_read(self.BASE+self.PAGE, 16))):
                    self.spare[spare_offset+i] &= byte
            else:
                block = offset // self.BLOCK * self.BLOCK
                self.storage[block:block+self.BLOCK] = b'\xff' * self.BLOCK
                spare_offset = block // self.PAGE * 16
                self.spare[spare_offset:spare_offset+32*16] = b'\xff' * (32*16)
        else:
            self.unsupported[command] += 1
            self.status = 0x88
        self.pending |= 6  # Observed completion masks; synchronous diagnostic model.

    def report(self):
        return {'model': 'MSM6250 NAND subset', 'synthetic_erased_image': self.synthetic,
                'manufacturer': '0x98', 'device': '0x76', 'size': self.SIZE,
                'commands': dict(self.commands), 'unsupported_commands': dict(self.unsupported),
                'direct_status_reads': self.direct_status_reads,
                'programmed_spare_bytes': len(self.spare)-self.spare.count(255),
                'factory_fixture': self.factory_fixture,
                'limitations': ['inferred completion bits', 'instant completion',
                               'no ECC', 'spare geometry inferred', 'no NAND CPU IRQ delivery', 'no persisted writes']}
