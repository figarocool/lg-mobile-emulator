"""LCD bus and inferred 176x220 GRAM window, recovered from firmware writes."""
from collections import Counter, deque
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_READ

class LcdBus:
    COMMAND = 0x20000000
    DATA = 0x20100000
    SUB_COMMAND = 0x30000000
    SUB_DATA = 0x30100000

    def __init__(self):
        self.selected = 0
        self.registers = {}
        self.counts = Counter()
        self.events = deque(maxlen=int(__import__('os').environ.get('U310_LCD_EVENTS', 256)))
        self.sub_selected = 0
        self.sub_registers = {}
        self.pixels = bytearray(176 * 220 * 2)
        self.x = 0
        self.y = 0
        self.pixel_writes = 0
        self.history_complete = True
        self.sub_log = deque(maxlen=4000)
        self.live_dir = None
        self.byte_pending = []
        self.byte_mode_writes = 0
        self.main_log = deque(maxlen=3000)
        self.main_data_count = 0
        self.sub_pixel_count = 0
        self.sub_pixels = bytearray(96 * 96 * 2)
        self.sub_pos = 0
        self.sub_frames = 0

    def attach(self, uc):
        for address in (self.COMMAND, self.DATA, self.SUB_COMMAND, self.SUB_DATA):
            uc.mem_map(address, 0x1000)
            uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self.access,
                        begin=address, end=address+3)

    def access(self, uc, access, address, size, value, _):
        sub = address in (self.SUB_COMMAND, self.SUB_DATA)
        command_port = self.SUB_COMMAND if sub else self.COMMAND
        selected = self.sub_selected if sub else self.selected
        registers = self.sub_registers if sub else self.registers
        if access == UC_MEM_READ:
            # Diagnostic register readback, not a confirmed panel ID/status response.
            value = selected if address == command_port else registers.get(selected, 0)
            uc.mem_write(address, value.to_bytes(4, 'little')[:size])
            self.counts['reads'] += 1
            return
        self.counts['writes'] += 1
        if address == command_port:
            if sub:
                self.sub_selected = value
            else:
                self.selected = value
                self.byte_pending = []
            selected = value
        else:
            if not sub and selected > 0xff and not selected & 0xff:
                self.byte_mode_data(selected >> 8, value >> 8)
                self.main_data_count += selected == 0x2200
                self.events.append({'port': hex(address), 'command': hex(selected), 'value': hex(value), 'size': size})
                return
            registers[selected] = value
            if not sub:
                if selected in (0x22, 0x2200):
                    self.main_data_count += 1
                else:
                    self.main_log.append((self.main_data_count, selected, value))
            if sub:
                if selected == 5:
                    self.sub_pixel_count += 1
                    if self.sub_pos < 96 * 96:
                        self.sub_pixels[self.sub_pos*2:self.sub_pos*2+2] = (value & 0xffff).to_bytes(2, 'little')
                        self.sub_pos += 1
                        if self.sub_pos == 96 * 96:
                            self.sub_frames += 1
                            self.publish('sub')
                else:
                    if selected == 6:  # window origin written before every observed frame
                        self.sub_pos = 0
                    self.sub_log.append((self.sub_pixel_count, selected, value))
            if not sub:
                if selected == 0x21:
                    self.x, self.y = value & 255, (value >> 8) & 255
                elif selected == 0x22:
                    if self.x < 176 and self.y < 220:
                        offset = (self.y * 176 + self.x) * 2
                        self.pixels[offset:offset+2] = (value & 0xffff).to_bytes(2, 'little')
                    self.pixel_writes += 1
                    if self.live_dir and self.pixel_writes % 9680 == 0:
                        self.publish('main')
                    horizontal = self.registers.get(0x44, 0xaf00)
                    vertical = self.registers.get(0x45, 0xdb00)
                    self.x += 1
                    # Original 0x158bd8 computes padding to four-pixel boundaries,
                    # and 0x158c8e aligns the cursor. R44 window endpoints
                    # therefore address four-pixel groups, not individual pixels.
                    if self.x > ((horizontal >> 8) | 3):
                        self.x = (horizontal & 255) & ~3
                        self.y += 1
                        if self.y > vertical >> 8:
                            self.y = vertical & 255
                            self.publish('main')
        self.events.append({'port': hex(address), 'command': hex(selected), 'value': hex(value), 'size': size})

    def report(self):
        return {'kind': 'diagnostic command/data capture', 'counts': dict(self.counts),
                'events': list(self.events), 'panel_model_verified': False,
                'gram_model': 'R21 cursor, four-pixel-aligned R44 window, R45 rows, R22 RGB565 pixels',
                'sub_log': list(self.sub_log), 'main_log': list(self.main_log), 'main_data_count': self.main_data_count, 'sub_pixel_count': self.sub_pixel_count, 'sub_frames': self.sub_frames, 'pixel_writes': self.pixel_writes, 'pixel_history_complete': self.history_complete}

    def byte_mode_data(self, register, byte):
        """Main panel byte interface: command is register<<8, each data write carries one
        byte in bits 15:8 (high byte first). Observed after the flip-open hypothesis; the
        low byte of each write is a constant 0x00/0x80 and is ignored."""
        self.byte_mode_writes += 1
        self.byte_pending.append(byte)
        if len(self.byte_pending) < 2:
            return
        word = (self.byte_pending[0] << 8) | self.byte_pending[1]
        self.byte_pending = []
        self.registers[register] = word
        if register == 0x21:
            self.x, self.y = word & 255, (word >> 8) & 255
        elif register == 0x22:
            self.put_pixel(word)

    def put_pixel(self, word):
        if self.x < 176 and self.y < 220:
            offset = (self.y * 176 + self.x) * 2
            self.pixels[offset:offset+2] = word.to_bytes(2, 'little')
        self.pixel_writes += 1
        if self.live_dir and self.pixel_writes % 9680 == 0:
            self.publish('main')  # partial updates never wrap the window: publish every quarter frame
        horizontal = self.registers.get(0x44, 0xaf00)
        vertical = self.registers.get(0x45, 0xdb00)
        self.x += 1
        if self.x > ((horizontal >> 8) | 3):
            self.x = (horizontal & 255) & ~3
            self.y += 1
            if self.y > vertical >> 8:
                self.y = vertical & 255
                self.publish('main')

    def publish(self, which):
        """Atomically write the latest completed frame for the live window."""
        if not self.live_dir:
            return
        target = self.live_dir / f'{which}.ppm'
        temporary = self.live_dir / f'{which}.tmp'
        (self.export if which == 'main' else self.export_sub)(temporary)
        temporary.replace(target)

    def export_sub(self, path):
        import struct
        rgb = bytearray()
        for (pixel,) in struct.iter_unpack('<H', self.sub_pixels):
            rgb.extend((((pixel >> 11) & 31)*255//31, ((pixel >> 5) & 63)*255//63, (pixel & 31)*255//31))
        path.write_bytes(b'P6\n96 96\n255\n'+rgb)

    def export(self, path):
        import struct
        rgb = bytearray()
        for (pixel,) in struct.iter_unpack('<H', self.pixels):
            rgb.extend((((pixel >> 11) & 31)*255//31, ((pixel >> 5) & 63)*255//63, (pixel & 31)*255//31))
        path.write_bytes(b'P6\n176 220\n255\n'+rgb)
