"""Model of the GRP, the display DMA controller (0x62800000) the firmware uses to push a RAM frame to the main LCD.

Recovered from the ARM driver (grp functions at 0xec9a62 .. 0xec9be8): a transfer is one 0x14-byte descriptor in a ring at
0x1e0c874 {+0 command 0x301, +4 source address, +8 destination port (the LCD data port), +0xc row bytes, +0xe rows, +0x10 source
stride}, submitted by writing the next ring index to register +0x18. The controller moves the rows to the panel and reports
completion through status bit 0 (+0x28) and its interrupt; the firmware's ISR (0xec99d0) acknowledges it through +0x2c and
signals the waiting task. Without that completion the driver's watchdog ("GRP time out") drops every frame.
"""
import struct
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_CPSR

from guest_call import call

BASE = 0x62800000
RING = 0x1e0c874
DESCRIPTOR = 0x14
ISR = 0xec99d0
LCD_DATA = 0x20100000


class GrpDma:
    def __init__(self, uc, panel):
        self.uc = uc
        self.panel = panel
        self.index = 0
        self.pending = []
        self.transfers = 0
        uc.hook_add(UC_HOOK_MEM_READ, self.read_index, begin=BASE + 0x18, end=BASE + 0x1b)
        uc.hook_add(UC_HOOK_MEM_WRITE, self.kick, begin=BASE + 0x18, end=BASE + 0x1b)
        uc.hook_add(UC_HOOK_MEM_WRITE, self.acknowledge, begin=BASE + 0x2c, end=BASE + 0x2f)

    def read_index(self, uc, access, address, size, value, _):
        self.index = int.from_bytes(uc.mem_read(BASE + 0x18, 4), 'little')

    def kick(self, uc, access, address, size, value, _):
        slot = RING + DESCRIPTOR * (self.index % 2)
        command, source, destination, row_bytes, rows, stride = struct.unpack('<IIIHHH', bytes(uc.mem_read(slot, 0x12)))
        if command & 0xffff == 0x301 and destination == LCD_DATA:
            self.copy(source, row_bytes, rows, stride or row_bytes)
        self.pending.append(1)

    def acknowledge(self, uc, access, address, size, value, _):
        # writing the status back to +0x2c clears the interrupt status
        uc.mem_write(BASE + 0x28, bytes(4))

    def copy(self, source, row_bytes, rows, stride):
        panel = self.panel
        data = b''.join(bytes(self.uc.mem_read(source + row * stride, row_bytes)) for row in range(rows))
        horizontal = panel.registers.get(0x44, 0xaf00)
        vertical = panel.registers.get(0x45, 0xdb00)
        x0, y0 = (horizontal & 255) & ~3, vertical & 255
        width = row_bytes // 2
        if x0 == 0 and y0 == 0 and width == 176 and rows * width <= 176 * 220:
            panel.pixels[:len(data)] = data
        else:
            for row in range(rows):
                y = y0 + row
                if y >= 220:
                    break
                for column in range(min(width, 176 - x0)):
                    offset = (y * 176 + x0 + column) * 2
                    panel.pixels[offset:offset + 2] = data[(row * width + column) * 2:(row * width + column) * 2 + 2]
        panel.pixel_writes += width * rows
        panel.publish('main')
        self.transfers += 1

    def service(self):
        """Complete queued transfers: status bit 0 and the firmware's own ISR, at a moment a task can be interrupted."""
        if not self.pending:
            return
        cpsr = self.uc.reg_read(UC_ARM_REG_CPSR)
        if cpsr & 0x1f != 0x13 or cpsr & 0x80:
            return
        self.pending.pop(0)
        self.uc.mem_write(BASE + 0x28, (1).to_bytes(4, 'little'))
        call(self.uc, ISR, thumb=True)
        self.uc.mem_write(BASE + 0x28, bytes(4))

    def report(self):
        return {'transfers': self.transfers}
