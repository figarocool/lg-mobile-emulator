"""Validate country metadata with the original ARM factory-field reader."""
import struct
import unittest
from ssikyu_crypto import CryptoProbe
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR


class CountryReaderTests(unittest.TestCase):
    def read_country(self, active=1, version=1, magic=0xc7c3b7ba):
        probe = CryptoProbe()
        u = probe.uc
        # Initialized factory-cache flag referenced by the original dispatcher.
        flag = struct.unpack('<I', bytes(u.mem_read(0x70f04, 4)))[0]
        u.mem_write(flag, b'\x01')
        header = struct.pack('<IIIIH', magic, 0xbdbab3c4, version, active, 1)
        u.mem_write(0x2285f50, header.ljust(512, b'\x00'))
        u.mem_write(probe.OUTPUT, b'\xcc'*2)
        u.reg_write(UC_ARM_REG_CPSR, 0xd3)
        u.reg_write(UC_ARM_REG_SP, probe.INPUT+0xff000)
        u.reg_write(UC_ARM_REG_LR, probe.RETURN|1)
        u.reg_write(UC_ARM_REG_R0, 38)
        u.reg_write(UC_ARM_REG_R1, probe.OUTPUT)
        u.emu_start(0x70e83, probe.RETURN, count=10000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC), probe.RETURN)
        return u.reg_read(UC_ARM_REG_R0), bytes(u.mem_read(probe.OUTPUT, 2))

    def test_original_reader_accepts_active_country(self):
        self.assertEqual(self.read_country(), (2, b'\x01\x00'))

    def test_original_reader_rejects_invalid_headers(self):
        for kwargs in [{'active': 0}, {'version': 2}, {'magic': 0}]:
            with self.subTest(**kwargs):
                self.assertEqual(self.read_country(**kwargs), (3, b'\xcc\xcc'))


if __name__ == '__main__':
    unittest.main()
