import unittest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_MEM_READ
from keypad import Keypad
from pathlib import Path
from unicorn.arm_const import UC_CPU_ARM_926, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_CPSR, UC_ARM_REG_R0, UC_ARM_REG_PC


class KeypadTests(unittest.TestCase):
    def setUp(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for base in (0x48000000, 0x84000000):
            self.uc.mem_map(base, 0x1000)
        self.keys = Keypad(self.uc)

    def rows(self, drive_a, drive_b=0):
        u, k = self.uc, self.keys
        u.mem_write(k.OUTPUT_A, drive_a.to_bytes(4, 'little'))
        u.mem_write(k.OUTPUT_B, drive_b.to_bytes(4, 'little'))
        k.read(u, UC_MEM_READ, k.INPUT, 4, 0, None)
        return int.from_bytes(u.mem_read(k.INPUT, 4), 'little')

    def test_idle_pullups_preserve_other_gpio(self):
        self.uc.mem_write(self.keys.INPUT, (0x12340000).to_bytes(4, 'little'))
        self.assertEqual(self.rows(0x7c40, 0x40000), 0x1234001f)

    def test_column_selection_and_release(self):
        self.keys.set_key(2, 0, True)
        self.keys.set_key(4, 6, True)
        self.assertEqual(self.rows(0x4000), 0x1b)
        self.assertEqual(self.rows(0x2000), 0x1f)
        self.assertEqual(self.rows(0, 0x40000), 0xf)
        self.assertEqual(self.rows(0x7c40, 0x40000), 0xb)
        self.keys.set_key(2, 0, False)
        self.assertEqual(self.rows(0x4000), 0x1f)

    def test_invalid_coordinates(self):
        with self.assertRaises(ValueError):
            self.keys.set_key(5, 0, True)

    def test_original_firmware_service_combination(self):
        data = next((Path(__file__).resolve().parents[1]/'firmware').glob('*CODE*')).read_bytes()
        for pressed, expected in [(False, 0), (True, 1)]:
            with self.subTest(pressed=pressed):
                u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
                u.ctl_set_cpu_model(UC_CPU_ARM_926)
                u.mem_map(0, 0x04000000)
                for base in (0x48000000, 0x84000000, 0x60000000):
                    u.mem_map(base, 0x1000)
                u.mem_write(0x5c000, data[0x24000:])
                keys = Keypad(u)
                if pressed:
                    for row, column in [(1, 0), (3, 0), (1, 2), (3, 2)]:
                        keys.set_key(row, column, True)
                u.reg_write(UC_ARM_REG_SP, 0x3000000)
                u.reg_write(UC_ARM_REG_LR, 0x3fff001)
                u.reg_write(UC_ARM_REG_CPSR, 0xd3)
                u.emu_start(0x1444043, 0x3fff000, count=20000)
                self.assertEqual(u.reg_read(UC_ARM_REG_PC), 0x3fff000)
                self.assertEqual(u.reg_read(UC_ARM_REG_R0), expected)


if __name__ == '__main__':
    unittest.main()
