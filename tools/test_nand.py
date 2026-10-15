"""Controller checks and execution of the original NAND discovery routine."""
import struct
import unittest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from emulator import run
from msm6250_nand import NandController

class NandTests(unittest.TestCase):
    def setUp(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.device = NandController()
        self.device.attach(self.uc)

    def test_identification_from_original_firmware(self):
        result = run('nand-init', True, 10000, True)
        self.assertEqual(result['return_value'], '0x0')
        data = bytes.fromhex(result['device_structure'])
        self.assertEqual(struct.unpack_from('<II', data, 0x78), (0x98, 0x76))
        self.assertEqual(result['nand']['commands'], {0: 1, 7: 1, 5: 1, 6: 1})

    def test_program_read_erase_and_one_to_zero(self):
        d, u = self.device, self.uc
        d.address = 512
        u.mem_write(d.BASE, b'\xaa' * 512)
        d.execute(u, 3)
        u.mem_write(d.BASE, b'\xff' * 512)
        d.execute(u, 3)
        d.execute(u, 1)
        self.assertEqual(bytes(u.mem_read(d.BASE, 528)), b'\xaa'*512 + b'\xff'*16)
        d.execute(u, 4)
        d.execute(u, 1)
        self.assertEqual(bytes(u.mem_read(d.BASE, 512)), b'\xff'*512)

    def test_bounds_and_invalid_dump(self):
        self.device.address = self.device.SIZE
        self.device.execute(self.uc, 1)
        self.assertEqual(self.device.status, 0x88)
        with self.assertRaises(ValueError):
            NandController(b'not a raw dump')

    def test_status_preserves_program_failure_and_spare_marker(self):
        d = self.device
        d.address = d.SIZE
        d.execute(self.uc, 3)
        d.execute(self.uc, 6)
        self.assertEqual(d.status, 0x88)
        d.address = 5
        d.execute(self.uc, 2)
        self.assertEqual(d.status, 0)
        self.assertEqual(d.spare_word, 0xffffffff)

    def test_spare_roundtrip_marker_and_erase(self):
        d, u = self.device, self.uc
        d.address = 512
        spare = b'\xff'*5 + b'\x00\x12\x34\x56' + b'\xff'*7
        u.mem_write(d.BASE, b'\xff'*512 + spare)
        d.execute(u, 3)
        u.mem_write(d.BASE, b'\x00'*528)
        d.execute(u, 1)
        self.assertEqual(bytes(u.mem_read(d.BASE+512, 16)), spare)
        d.address = 517
        d.execute(u, 2)
        self.assertEqual(d.spare_word, 0x56341200)
        d.address = 512
        d.execute(u, 4)
        d.execute(u, 1)
        self.assertEqual(bytes(u.mem_read(d.BASE+512, 16)), b'\xff'*16)

    def test_direct_status_port(self):
        from unicorn import UC_MEM_WRITE, UC_MEM_READ
        d, u = self.device, self.uc
        d._memory(u, UC_MEM_WRITE, d.DIRECT, 1, 0x74, None)
        d._memory(u, UC_MEM_READ, d.DIRECT, 2, 0, None)
        self.assertEqual(int.from_bytes(u.mem_read(d.DIRECT, 2), 'little') & 3, 0)
        d.status = 0x88
        d._memory(u, UC_MEM_READ, d.DIRECT, 2, 0, None)
        self.assertEqual(int.from_bytes(u.mem_read(d.DIRECT, 2), 'little') & 3, 1)

    def test_mmio_command_and_ack_executed_by_arm(self):
        u, d = self.uc, self.device
        u.mem_map(0x1000, 0x1000)
        # ldr r0, literal command address; mov r1,#7; str r1,[r0];
        # ldr r0, literal IRQ address; ldr r2,[r0]; mov r1,#6;
        # str r1,[r0,#8]; ldr r3,[r0].
        words = [0xe59f0018, 0xe3a01007, 0xe5801000, 0xe59f0010,
                 0xe5902000, 0xe3a01006, 0xe5801008, 0xe5903000,
                 d.BASE+0x300, d.IRQ]
        u.mem_write(0x1000, struct.pack('<10I', *words))
        u.emu_start(0x1000, 0x1020)
        from unicorn.arm_const import UC_ARM_REG_R2, UC_ARM_REG_R3
        self.assertEqual(u.reg_read(UC_ARM_REG_R2), 6)
        self.assertEqual(u.reg_read(UC_ARM_REG_R3), 0)

if __name__ == '__main__':
    unittest.main()
