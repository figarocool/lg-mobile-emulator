"""Execute original mmc_stop_clock() against the inferred status bit."""
from pathlib import Path
import unittest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_CPSR, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_R0, UC_CPU_ARM_926
from mmc_clock import MmcClock

class MmcTests(unittest.TestCase):
    def test_firmware_stop_clock_completes(self):
        u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        u.ctl_set_cpu_model(UC_CPU_ARM_926)
        u.mem_map(0x1000, 0x2000)
        u.mem_map(0x10f0000, 0x2000)
        u.mem_map(MmcClock.BASE, 0x1000)
        data = next((Path(__file__).resolve().parents[1]/'firmware').glob('*CODE*')).read_bytes()
        u.mem_write(0x10f0000, data[0x10b8000:0x10ba000])
        device = MmcClock()
        device.attach(u)
        u.reg_write(UC_ARM_REG_CPSR, 0xd3)
        u.reg_write(UC_ARM_REG_SP, 0x1800)
        u.reg_write(UC_ARM_REG_LR, 0x2001)
        u.emu_start(0x10f0e79, 0x2000, count=100)
        self.assertEqual(u.reg_read(UC_ARM_REG_R0), 1)
        self.assertTrue(device.stopped)
        self.assertEqual(device.stops, 1)

if __name__ == '__main__':
    unittest.main()
