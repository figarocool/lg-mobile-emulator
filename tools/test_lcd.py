import unittest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_MEM_WRITE
from lcd_bus import LcdBus

class LcdTests(unittest.TestCase):
    def setUp(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.panel = LcdBus()
        self.panel.attach(self.uc)

    def register(self, index, value):
        p = self.panel
        p.access(self.uc, UC_MEM_WRITE, p.COMMAND, 2, index, None)
        p.access(self.uc, UC_MEM_WRITE, p.DATA, 2, value, None)

    def test_window_cursor_and_wrap(self):
        self.register(0x21, 2 << 8)
        self.register(0x44, 3 << 8)
        self.register(0x45, 3 << 8 | 2)
        colors = [0xf800, 0x07e0, 0x001f, 0xffff]*2
        for value in colors:
            self.register(0x22, value)
        p = self.panel
        self.assertEqual((p.x, p.y), (0, 2))
        for index, value in enumerate(colors):
            off = ((2+index//4)*176+index%4)*2
            self.assertEqual(int.from_bytes(p.pixels[off:off+2], 'little'), value)
        self.assertEqual(p.pixel_writes, 8)

    def test_original_diagnostic_rectangle_alignment(self):
        # Original driver programs 20..154, sends 136 pixels per row:
        # 0x158bd8 pads the right edge and 0x158c8e aligns the cursor.
        self.register(0x21, 177 << 8 | 20)
        self.register(0x44, 154 << 8 | 20)
        self.register(0x45, 213 << 8 | 177)
        for row in range(37):
            for x in range(136):
                self.register(0x22, row+1)
        self.assertEqual((self.panel.x, self.panel.y), (20, 177))
        for row in range(37):
            for x in range(20,156):
                off = ((177+row)*176+x)*2
                self.assertEqual(int.from_bytes(self.panel.pixels[off:off+2], 'little'), row+1)

    def test_secondary_bus_does_not_corrupt_main_pixels(self):
        p = self.panel
        p.access(self.uc, UC_MEM_WRITE, p.SUB_COMMAND, 2, 0x22, None)
        p.access(self.uc, UC_MEM_WRITE, p.SUB_DATA, 2, 0xffff, None)
        self.assertEqual(p.pixel_writes, 0)
        self.assertFalse(any(p.pixels))

if __name__ == '__main__':
    unittest.main()
