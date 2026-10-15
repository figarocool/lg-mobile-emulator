import tempfile
import unittest
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_MEM_WRITE, UC_MEM_READ
from keypad import Keypad
from lcd_bus import LcdBus


class SecondaryPanelTests(unittest.TestCase):
    def setUp(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.panel = LcdBus()
        self.panel.attach(self.uc)

    def sub(self, register, value):
        p = self.panel
        p.access(self.uc, UC_MEM_WRITE, p.SUB_COMMAND, 2, register, None)
        p.access(self.uc, UC_MEM_WRITE, p.SUB_DATA, 2, value, None)

    def test_frame_starts_at_register_6_and_completes_after_9216_pixels(self):
        self.sub(0x06, 0)
        for index in range(96 * 96):
            self.sub(0x05, index & 0xffff)
        self.assertEqual(self.panel.sub_frames, 1)
        self.assertEqual(int.from_bytes(self.panel.sub_pixels[2:4], 'little'), 1)
        last = (96 * 96 - 1) * 2
        self.assertEqual(int.from_bytes(self.panel.sub_pixels[last:last+2], 'little'), (96 * 96 - 1) & 0xffff)

    def test_register_6_restarts_an_incomplete_frame(self):
        self.sub(0x06, 0)
        for _ in range(100):
            self.sub(0x05, 0xffff)
        self.sub(0x06, 0)
        self.sub(0x05, 0x1234)
        self.assertEqual(int.from_bytes(self.panel.sub_pixels[:2], 'little'), 0x1234)
        self.assertEqual(self.panel.sub_frames, 0)


class MainByteInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.panel = LcdBus()
        self.panel.attach(self.uc)

    def byte_write(self, register, *data):
        p = self.panel
        p.access(self.uc, UC_MEM_WRITE, p.COMMAND, 2, register << 8, None)
        for byte in data:
            p.access(self.uc, UC_MEM_WRITE, p.DATA, 2, byte << 8 | 0x80, None)

    def test_register_composed_from_two_bytes_high_first(self):
        self.byte_write(0x44, 0x03, 0x00)
        self.assertEqual(self.panel.registers[0x44], 0x0300)

    def test_pixels_use_two_bytes_and_ignore_low_byte_noise(self):
        self.byte_write(0x21, 0, 0)
        self.byte_write(0x44, 0x03, 0x00)
        self.byte_write(0x45, 0x01, 0x00)
        self.byte_write(0x22, 0xe7, 0x3d, 0xef, 0x5d)
        self.assertEqual(int.from_bytes(self.panel.pixels[0:2], 'little'), 0xe73d)
        self.assertEqual(int.from_bytes(self.panel.pixels[2:4], 'little'), 0xef5d)
        self.assertEqual(self.panel.pixel_writes, 2)

    def test_new_command_discards_half_a_pixel(self):
        self.byte_write(0x22, 0xaa)
        self.byte_write(0x22, 0x12, 0x34)
        self.assertEqual(int.from_bytes(self.panel.pixels[0:2], 'little'), 0x1234)


class LiveKeysTests(unittest.TestCase):
    def setUp(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for base in (0x48000000, 0x84000000):
            self.uc.mem_map(base, 0x1000)
        self.directory = tempfile.TemporaryDirectory()
        self.file = Path(self.directory.name) / 'keys.txt'
        self.now = 0.0
        self.keys = Keypad(self.uc, self.file, lambda: self.now)

    def tearDown(self):
        self.directory.cleanup()

    def sense(self):
        self.keys.read_sense(self.uc, UC_MEM_READ, self.keys.SENSE, 4, 0, None)
        return int.from_bytes(self.uc.mem_read(self.keys.SENSE, 4), 'little')

    def test_power_key_line_is_high_at_rest_and_low_while_held(self):
        self.assertEqual(self.sense() & self.keys.SENSE_BIT, self.keys.SENSE_BIT)
        self.file.write_text('P')
        self.assertEqual(self.sense() & self.keys.SENSE_BIT, 0)
        self.assertEqual(self.keys.pressed, set())
        import os
        self.file.write_text('')
        os.utime(self.file, ns=(1, self.keys.keys_mtime + 1))
        self.assertEqual(self.sense() & self.keys.SENSE_BIT, self.keys.SENSE_BIT)

    def test_matrix_keys_from_file_do_not_touch_the_power_line(self):
        self.file.write_text('0,5 2,6')
        self.assertEqual(self.sense() & self.keys.SENSE_BIT, self.keys.SENSE_BIT)
        self.assertEqual(self.keys.pressed, {(0, 5), (2, 6)})

    def test_invalid_file_content_is_ignored(self):
        self.file.write_text('9,9 x,y')
        self.sense()
        self.assertEqual(self.keys.pressed, set())


if __name__ == '__main__':
    unittest.main()


class MinimumHoldTests(unittest.TestCase):
    def setUp(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for base in (0x48000000, 0x84000000):
            self.uc.mem_map(base, 0x1000)
        self.directory = tempfile.TemporaryDirectory()
        self.file = Path(self.directory.name) / 'keys.txt'
        self.now = 0.0
        self.keys = Keypad(self.uc, self.file, lambda: self.now)

    def tearDown(self):
        self.directory.cleanup()

    def write(self, text, stamp):
        import os
        self.file.write_text(text)
        os.utime(self.file, ns=(stamp, stamp))
        self.keys.poll_keys_file()

    def test_a_short_tap_stays_down_for_the_minimum_hold(self):
        self.write('2,3', 1)
        self.assertEqual(self.keys.pressed, {(2, 3)})
        self.write('', 2)            # released immediately
        self.now = 0.03
        self.keys.poll_keys_file()
        self.assertEqual(self.keys.pressed, {(2, 3)})
        self.now = 0.2
        self.keys.poll_keys_file()
        self.assertEqual(self.keys.pressed, set())

    def test_a_long_hold_is_not_cut_short(self):
        self.write('2,3', 1)
        self.now = 5.0
        self.keys.poll_keys_file()
        self.assertEqual(self.keys.pressed, {(2, 3)})
