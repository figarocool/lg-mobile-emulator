import unittest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_CPSR, UC_ARM_REG_SP, UC_ARM_REG_PC, UC_ARM_REG_R2
from timer_irq import TimerIRQ, enter_irq

class TimerTests(unittest.TestCase):
    def setUp(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.mem_map(0x84000000, 0x1000)
        self.timer = TimerIRQ()
        self.timer.attach(self.uc)
        self.uc.reg_write(UC_ARM_REG_CPSR, 0x13)
        self.timer.period = 164
        self.timer.deadline = self.timer.period_cycles()

    def test_masking_and_idle_clock(self):
        self.assertFalse(self.timer.advance(idle=True))
        self.assertEqual(self.timer.fast_forwards, 0)
        self.uc.mem_write(self.timer.MASK, (1).to_bytes(4, 'little'))
        self.assertTrue(self.timer.advance(idle=True))
        self.assertEqual(self.timer.raised, 1)
        self.uc.reg_write(UC_ARM_REG_CPSR, 0x93)
        self.assertFalse(self.timer.advance())

    def test_no_reentry_before_ack(self):
        self.uc.mem_write(self.timer.MASK, (1).to_bytes(4, 'little'))
        self.assertTrue(self.timer.advance(idle=True))
        self.timer.inflight = True
        self.assertFalse(self.timer.advance())
        from unicorn import UC_MEM_WRITE
        self.timer.memory(self.uc, UC_MEM_WRITE, self.timer.ACK, 4, 1, None)
        self.assertFalse(self.timer.pending)
        self.assertFalse(self.timer.inflight)
        self.assertEqual(self.timer.acks, 1)

    def test_irq_exception_return_restores_thumb_and_stack_bank(self):
        u = self.uc
        u.mem_map(0x1000, 0x3000)
        u.mem_write(0x1018, bytes.fromhex('2a20a0e304f05ee2'))  # mov r2,#42; subs pc,lr,#4
        u.reg_write(UC_ARM_REG_CPSR, 0x92)
        u.reg_write(UC_ARM_REG_SP, 0x2000)
        u.reg_write(UC_ARM_REG_CPSR, 0x33)
        u.reg_write(UC_ARM_REG_SP, 0x3000)
        u.reg_write(UC_ARM_REG_PC, 0x3001)
        self.assertTrue(enter_irq(u, 0x1000))
        self.assertEqual(u.reg_read(UC_ARM_REG_SP), 0x2000)
        u.emu_start(0x1018, 0, count=2)
        self.assertEqual(u.reg_read(UC_ARM_REG_R2), 42)
        self.assertEqual(u.reg_read(UC_ARM_REG_CPSR), 0x33)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC), 0x3000)
        self.assertEqual(u.reg_read(UC_ARM_REG_SP), 0x3000)

if __name__ == '__main__':
    unittest.main()
