"""U880 diagnostic GRAM inferred from V10b drawing routine at 0xf384c.

R20/R21 set separate column/row cursors. R50..R53 bound the rectangle;
the original driver adds 0x60 to row addresses. Panel timing/ID are unknown.
"""
from unicorn import UC_MEM_READ
from lcd_bus import LcdBus


class U880LcdBus(LcdBus):
    ROW_ORIGIN = 0x60

    def access(self, uc, access, address, size, value, extra):
        if address in (self.SUB_COMMAND, self.SUB_DATA):
            return super().access(uc, access, address, size, value, extra)
        if access == UC_MEM_READ:
            # Diagnostic register readback only, as on the common LCD bus.
            result = self.selected if address == self.COMMAND else self.registers.get(self.selected, 0)
            uc.mem_write(address, result.to_bytes(4, 'little')[:size])
            self.counts['reads'] += 1
            return
        self.counts['writes'] += 1
        if address == self.COMMAND:
            self.selected = value
            self.byte_pending = []
        else:
            if self.selected > 0xff and not self.selected & 0xff:
                self.byte_mode_data(self.selected >> 8, (value >> 8) & 0xff)
            else:
                self.write_register(self.selected, value)
        self.events.append({'port': hex(address), 'command': hex(self.selected), 'value': hex(value), 'size': size})

    def write_register(self, register, value):
        self.registers[register] = value
        if register == 0x20:
            self.x = value
        elif register == 0x21:
            self.y = value-self.ROW_ORIGIN
        elif register == 0x22:
            self.main_data_count += 1
            self.put_pixel(value & 0xffff)
        if register != 0x22:
            self.main_log.append((self.main_data_count, register, value))

    def byte_mode_data(self, register, byte):
        """Same U880 registers over the observed high-byte-first 8-bit bus."""
        self.byte_mode_writes += 1
        self.byte_pending.append(byte)
        if len(self.byte_pending) == 2:
            value = (self.byte_pending[0] << 8) | self.byte_pending[1]
            self.byte_pending = []
            self.write_register(register, value)

    def put_pixel(self, word):
        physical_y = self.y+self.ROW_ORIGIN
        sub = 0 <= physical_y < 96 and 40 <= self.x < 136
        if sub:
            # Runtime writes select the external 96x96 viewport at x=40..135,
            # y=0..95 on the same GRAM bus as main rows 96..315.
            offset = (physical_y*96+self.x-40)*2
            self.sub_pixels[offset:offset+2] = word.to_bytes(2, 'little')
            self.sub_pixel_count += 1
        elif 0 <= self.x < 176 and 0 <= self.y < 220:
            offset = (self.y*176+self.x)*2
            self.pixels[offset:offset+2] = word.to_bytes(2, 'little')
        self.pixel_writes += 1
        self.x += 1
        if self.x > self.registers.get(0x51, 175):
            self.x = self.registers.get(0x50, 0)
            self.y += 1
            if self.y > self.registers.get(0x53, self.ROW_ORIGIN+219)-self.ROW_ORIGIN:
                self.y = self.registers.get(0x52, self.ROW_ORIGIN)-self.ROW_ORIGIN
                if sub:
                    self.sub_frames += 1
                self.publish('sub' if sub else 'main')

    def report(self):
        result = super().report()
        result['gram_model'] = 'U880 R20 column, R21 row +0x60, R50..R53 window, R22 RGB565; inferred'
        result['sub_panel_verified'] = False
        result['byte_mode_data_writes'] = self.byte_mode_writes
        result['shared_gram_sub_window'] = 'Observed runtime viewport x=40..135, y=0..95; inferred physical layout'
        return result
