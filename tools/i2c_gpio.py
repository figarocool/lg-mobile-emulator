"""The phone's I2C bus (camera sensor control) as seen by the firmware's own I2C service.

The service in the firmware (i2c.c) drives an I2C controller at 0x84001100 and exposes two entry points that take a command record:
read at 0x144355e and write at 0x14436c0 (reached through the veneers 0xd9ab00 / 0xd9aaf4). The record is: +0 bus, +1 slave
address (8-bit form), +2 options (bit 1 / bit 2: 16 / 8-bit register address), +4 data buffer, +8 register address, +0xa byte count,
+0xc bytes transferred (output). The functions return 0 on success and a non-zero code on failure.

Here the transfers are completed at that level: the slave device model gets the register address and the bytes, the buffer and the
count are filled in as the controller would have, and the function returns to its caller. The slave devices model the chips that answer
on the bus (the camera sensor). This replaces the controller registers, not the firmware's camera driver, which runs unchanged.
"""
import struct

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0

READ_ENTRY, WRITE_ENTRY = 0x144355e, 0x14436c0
ERROR_NO_ACK = 4


class SccbSensor:
    """OmniVision-style register file (8-bit register address, 8-bit data): the ID registers the driver probes."""

    def __init__(self, registers=None):
        self.registers = {0x0a: 0x96, 0x0b: 0x57, 0x1c: 0x7f, 0x1d: 0xa2}   # PID, VER, MIDH, MIDL of an OV9655
        self.registers.update(registers or {})
        self.writes = []

    def write_register(self, index, value):
        self.registers[index & 0xffff] = value
        self.writes.append((index & 0xffff, value))

    def read_register(self, index):
        return self.registers.get(index & 0xffff, 0)


class I2cService:
    def __init__(self, uc, devices):
        self.uc = uc
        self.devices = devices          # (bus, 7-bit address) -> device
        self.log = []
        uc.hook_add(UC_HOOK_CODE, self.read, begin=READ_ENTRY, end=READ_ENTRY)
        uc.hook_add(UC_HOOK_CODE, self.write, begin=WRITE_ENTRY, end=WRITE_ENTRY)

    def command(self, uc):
        record = uc.reg_read(UC_ARM_REG_R0)
        raw = bytes(uc.mem_read(record, 16))
        bus, address, options = raw[0], raw[1] >> 1, raw[2]
        buffer, register, count = struct.unpack('<IHH', raw[4:12])
        return record, bus, address, options, buffer, register, count

    def finish(self, uc, record, count, code):
        uc.mem_write(record + 0xc, count.to_bytes(2, 'little'))
        uc.reg_write(UC_ARM_REG_R0, code)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def read(self, uc, address_, size, _):
        record, bus, address, options, buffer, register, count = self.command(uc)
        device = self.devices.get((bus, address))
        self.log.append(('read', bus, address, register, count, device is not None))
        if device is None:
            return self.finish(uc, record, 0, ERROR_NO_ACK)
        data = bytes(device.read_register(register + i) & 0xff for i in range(count))
        uc.mem_write(buffer, data)
        self.finish(uc, record, count, 0)

    def write(self, uc, address_, size, _):
        record, bus, address, options, buffer, register, count = self.command(uc)
        device = self.devices.get((bus, address))
        self.log.append(('write', bus, address, register, count, device is not None))
        if device is None:
            return self.finish(uc, record, 0, ERROR_NO_ACK)
        for i, value in enumerate(bytes(uc.mem_read(buffer, count))):
            device.write_register(register + i, value)
        self.finish(uc, record, count, 0)

    def report(self):
        return {'commands': len(self.log), 'last': self.log[-12:]}
