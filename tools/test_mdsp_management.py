import unittest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_MEM_WRITE, UC_MEM_READ
from mdsp_management import MdspManagement
from timer_irq import TimerIRQ
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR, UC_CPU_ARM_926
import tempfile
import checkpoint
from keypad import Keypad


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.ctl_set_cpu_model(UC_CPU_ARM_926)
        for base in (0x50206000, 0x5040b000, 0x50c00000, 0x84000000):
            self.uc.mem_map(base, 0x1000)
        self.irq = TimerIRQ()
        self.irq.attach(self.uc)
        self.dsp = MdspManagement(self.uc, self.irq)

    def test_management_reply_latches_masked_irq_and_w1c(self):
        u, d, t = self.uc, self.dsp, self.irq
        u.mem_write(d.COMMAND, b'\x01\x00')
        u.mem_write(d.REQUEST_MASK, (0x1234).to_bytes(4, 'little'))
        d.initialize_after_restore()
        d.advance()
        self.assertEqual(d.command(), 0)
        self.assertEqual(bytes(u.mem_read(d.RESPONSE_MASK, 4)), (0x1234).to_bytes(4, 'little'))
        self.assertEqual(t.pending_bits(), 32)
        self.assertEqual(t.enabled_bits(), 0)
        u.mem_write(t.MASK, (32).to_bytes(4, 'little'))
        t.memory(u, UC_MEM_READ, t.VECTORS[0], 4, 0, None)
        self.assertEqual(int.from_bytes(u.mem_read(t.VECTORS[0], 4), 'little'), 5)
        t.pending = True
        t.memory(u, UC_MEM_WRITE, t.ACK, 4, 32, None)
        self.assertEqual(t.pending_bits(), 1)  # Acknowledge only the selected source.

    def test_unknown_command_remains_pending(self):
        self.uc.mem_write(self.dsp.COMMAND, b'\x04\x00')
        self.dsp.initialize_after_restore()
        self.dsp.advance()
        self.assertEqual(self.dsp.command(), 4)
        self.assertEqual(self.irq.pending_bits(), 0)
        self.assertEqual(self.dsp.unsupported[4], 1)

    def test_reply_requires_doorbell(self):
        self.uc.mem_write(self.dsp.COMMAND, b'\x01\x00')
        self.dsp.advance()
        self.assertEqual(self.dsp.command(), 1)

    def test_boot_ready_requires_release_sequence(self):
        u, d = self.uc, self.dsp
        d.control(u, UC_MEM_WRITE, d.CONTROL, 4, 0x3b, None)
        d.boot_status(u, UC_MEM_READ, d.BOOT_STATUS, 2, 0, None)
        self.assertEqual(bytes(u.mem_read(d.BOOT_STATUS, 2)), b'\x00\x00')
        d.control(u, UC_MEM_WRITE, d.CONTROL, 4, 0x1b, None)
        d.control(u, UC_MEM_WRITE, d.CONTROL, 4, 0x3b, None)
        d.boot_status(u, UC_MEM_READ, d.BOOT_STATUS, 2, 0, None)
        self.assertEqual(bytes(u.mem_read(d.BOOT_STATUS, 2)), b'\x01\x00')
        self.assertEqual(d.boot_replies, 1)
        u.mem_write(d.BOOT_STATUS, b'\x00\x00')
        d.boot_status(u, UC_MEM_READ, d.BOOT_STATUS, 2, 0, None)
        self.assertEqual(bytes(u.mem_read(d.BOOT_STATUS, 2)), b'\x00\x00')

    def test_original_arm_handler_checks_reply(self):
        """Run the actual completion predicate, stopping before REX side effects."""
        u = self.uc
        u.mem_map(0, 0x04000000)
        data = next((Path(__file__).resolve().parents[1]/'firmware').glob('*CODE*')).read_bytes()
        u.mem_write(0x5c000, data[0x24000:])
        reached = []
        def stop_at_rex(uc, address, size, user):
            reached.append(address)
            uc.emu_stop()
        u.hook_add(UC_HOOK_CODE, stop_at_rex, begin=0x4958b4, end=0x4958b4)
        def run_handler(command, response):
            u.mem_write(0x19a3970, b'\x02')
            u.mem_write(0x19a3980, (4).to_bytes(4, 'little'))
            u.mem_write(self.dsp.COMMAND, command.to_bytes(2, 'little'))
            u.mem_write(self.dsp.RESPONSE_MASK, response.to_bytes(4, 'little'))
            u.reg_write(UC_ARM_REG_SP, 0x3000000)
            u.reg_write(UC_ARM_REG_LR, 0x3fff001)
            u.emu_start(0x48288d, 0x3fff000, count=100)
        run_handler(1, 4)
        run_handler(0, 0)
        self.assertEqual(reached, [])
        run_handler(0, 4)
        self.assertEqual(reached, [0x4958b4])

    def test_snapshot_preserves_pending_device_work(self):
        self.uc.mem_map(0x48000000, 0x1000)
        keys = Keypad(self.uc)
        keys.set_key(2, 0, True)
        self.dsp.control(self.uc, UC_MEM_WRITE, self.dsp.CONTROL, 4, 0x1b, None)
        self.dsp.control(self.uc, UC_MEM_WRITE, self.dsp.CONTROL, 4, 0x3b, None)
        self.uc.mem_write(self.dsp.COMMAND, b'\x01\x00')
        self.uc.mem_write(self.dsp.REQUEST_MASK, (4).to_bytes(4, 'little'))
        self.dsp.doorbell = True
        self.irq.raise_source(7)
        config = {'irq': True, 'mdsp_management': True, 'keypad': True}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'snapshot.zip'
            checkpoint.save(path, self.uc, config, None, None, [], 0,
                            self.irq, None, self.dsp, keys)
            self.dsp.boot_pending = False
            self.dsp.doorbell = False
            self.irq.peripheral_pending = 0
            keys.pressed.clear()
            checkpoint.restore(path, self.uc, config, None, None, lambda page: None,
                               self.irq, None, self.dsp, keys)
        self.assertEqual(keys.pressed, {(2, 0)})
        self.assertTrue(self.dsp.boot_pending)
        self.dsp.advance()
        self.assertEqual(self.dsp.command(), 0)
        self.assertEqual(self.irq.peripheral_pending, (1 << 7) | (1 << 5))


if __name__ == '__main__':
    unittest.main()
