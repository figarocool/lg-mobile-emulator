"""Check LCD coordinates against an original U880 V10b drawing instruction sequence."""
import hashlib
import struct
import unittest
import tempfile
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_MEM_WRITE
from unicorn.arm_const import (UC_CPU_ARM_926, UC_ARM_REG_CPSR, UC_ARM_REG_SP,
                               UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                               UC_ARM_REG_PC)
from u880_lcd import U880LcdBus


class OriginalDrawingTests(unittest.TestCase):
    def test_checkpoint_preserves_pending_high_pixel_byte(self):
        import checkpoint
        def machine():
            uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
            uc.mem_map(0x10000, 4096)
            panel = U880LcdBus()
            panel.attach(uc)
            return uc, panel
        uc, panel = machine()
        panel.x, panel.y = 2, 5
        panel.selected = 0x2200
        panel.byte_mode_data(0x22, 0xf8)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'half-pixel.zip'
            checkpoint.save(path, uc, {}, None, panel, (), 0)
            restored_uc, restored = machine()
            checkpoint.restore(path, restored_uc, {}, None, restored, lambda page: None)
        restored.byte_mode_data(0x22, 0)
        offset = (5*176+2)*2
        self.assertEqual(restored.pixels[offset:offset+2], b'\x00\xf8')
        self.assertEqual(restored.byte_pending, [])
        self.assertEqual(restored.byte_mode_writes, 2)

    def test_runtime_byte_interface_keeps_u880_separate_coordinates(self):
        uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        panel = U880LcdBus()
        panel.attach(uc)
        def word(register, value):
            panel.access(uc, UC_MEM_WRITE, panel.COMMAND, 2, register << 8, None)
            panel.access(uc, UC_MEM_WRITE, panel.DATA, 2, value & 0xff00, None)
            panel.access(uc, UC_MEM_WRITE, panel.DATA, 2, ((value & 255) << 8)|0x80, None)
        for register, value in ((0x20, 2), (0x21, 101), (0x50, 2),
                                (0x51, 3), (0x52, 101), (0x53, 101)):
            word(register, value)
        word(0x22, 0xf800)
        word(0x22, 0x07e0)
        self.assertEqual(panel.pixels[(5*176+2)*2:(5*176+4)*2], b'\x00\xf8\xe0\x07')
        self.assertEqual(panel.sub_pixel_count, 0)

    def test_shared_gram_external_window_preserves_main_panel(self):
        uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        panel = U880LcdBus()
        panel.attach(uc)
        def register(command, value):
            panel.access(uc, UC_MEM_WRITE, panel.COMMAND, 2, command, None)
            panel.access(uc, UC_MEM_WRITE, panel.DATA, 2, value, None)
        for command, value in ((0x20, 40), (0x21, 0), (0x50, 40),
                               (0x51, 41), (0x52, 0), (0x53, 1)):
            register(command, value)
        for color in (0xf800, 0x07e0, 0x001f, 0xffff):
            register(0x22, color)
        self.assertEqual(panel.sub_pixels[:4], b'\x00\xf8\xe0\x07')
        self.assertEqual(panel.sub_pixels[192:196], b'\x1f\x00\xff\xff')
        self.assertEqual(panel.pixels, bytes(176*220*2))
        self.assertEqual(panel.sub_pixel_count, 4)
        self.assertEqual(panel.sub_frames, 1)

    def test_original_rectangle_body_writes_expected_pixels(self):
        path = Path(__file__).resolve().parents[1]/'analysis/u880_decoded/v10b/amss.bin'
        if not path.exists():
            self.skipTest('Local decoded U880 V10b firmware unavailable')
        image = path.read_bytes()
        self.assertEqual(hashlib.sha256(image).hexdigest(),
                         '95dfa53aee43bd97aba158878e655adeb0d9b3fc0f02c13efb30319c0a29f9d0')
        uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        uc.ctl_set_cpu_model(UC_CPU_ARM_926)
        uc.mem_map(0xc0000, (len(image)+4095)&~4095)
        uc.mem_write(0xc0000, image)
        uc.mem_map(0x4000000, 4096)
        panel = U880LcdBus()
        panel.attach(uc)
        # Isolate original bus-write body (after the OS lock, before unlock).
        # Locals describe x=2..3, y=5..6, four red pixels. No instructions patched.
        uc.reg_write(UC_ARM_REG_CPSR, 0xd3)
        uc.reg_write(UC_ARM_REG_SP, 0x4000000)
        uc.mem_write(0x4000004, struct.pack('<II', 5, 6))
        for reg, value in ((UC_ARM_REG_R4, 4), (UC_ARM_REG_R5, 0xf800),
                           (UC_ARM_REG_R6, 2), (UC_ARM_REG_R7, 3)):
            uc.reg_write(reg, value)
        uc.emu_start(0xf3879, 0xf38c8, count=1000)
        self.assertEqual(uc.reg_read(UC_ARM_REG_PC), 0xf38c8)
        expected = bytearray(176*220*2)
        for x, y in ((2, 5), (3, 5), (2, 6), (3, 6)):
            offset = (y*176+x)*2
            expected[offset:offset+2] = b'\x00\xf8'
        self.assertEqual(panel.pixels, expected)
        self.assertEqual(panel.pixel_writes, 4)


if __name__ == '__main__':
    unittest.main()
