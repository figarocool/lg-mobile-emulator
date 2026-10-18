"""Exercise original U880 service-key detection against the shared GPIO model."""
from pathlib import Path
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import (UC_CPU_ARM_926, UC_ARM_REG_SP, UC_ARM_REG_LR,
                               UC_ARM_REG_CPSR, UC_ARM_REG_R0, UC_ARM_REG_PC)
from keypad import Keypad


class OriginalKeyScanTests(unittest.TestCase):
    def test_original_service_combination_both_versions(self):
        root = Path(__file__).resolve().parents[1]
        for version, function in (('v10b', 0x1359c68), ('v10a', 0x45a860)):
            path = root/'analysis/u880_decoded'/version/'amss.bin'
            if not path.exists():
                self.skipTest('Local U880 decoded firmware unavailable')
            image = path.read_bytes()
            for pressed, expected in ((False, 0), (True, 1)):
                with self.subTest(version=version, pressed=pressed):
                    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
                    uc.ctl_set_cpu_model(UC_CPU_ARM_926)
                    uc.mem_map(0, 0x4000000)
                    uc.mem_write(0xc0000, image)
                    for base in (0x48000000, 0x84000000, 0x60000000):
                        uc.mem_map(base, 4096)
                    keys = Keypad(uc)
                    if pressed:
                        for row, column in ((1, 0), (3, 0), (1, 2), (3, 2)):
                            keys.set_key(row, column, True)
                    uc.reg_write(UC_ARM_REG_SP, 0x3000000)
                    uc.reg_write(UC_ARM_REG_LR, 0x3fff001)
                    uc.reg_write(UC_ARM_REG_CPSR, 0xd3)
                    uc.emu_start(function|1, 0x3fff000, count=20000)
                    self.assertEqual(uc.reg_read(UC_ARM_REG_PC), 0x3fff000)
                    self.assertEqual(uc.reg_read(UC_ARM_REG_R0), expected)


if __name__ == '__main__':
    unittest.main()
