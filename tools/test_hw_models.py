"""Tests of the hardware models added for the network, SD write path, earphone jack and camera I2C."""
import struct
import tempfile
import unittest
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0

import gpio_inputs
import i2c_gpio
import mmc_card
import mmc_controller
import netsim


def machine(*pages):
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    for page in pages:
        uc.mem_map(page, 0x1000)
    return uc


class I2cServiceTests(unittest.TestCase):
    def setUp(self):
        self.uc = machine(0x01000000, 0x02000000)
        self.sensor = i2c_gpio.SccbSensor()
        self.service = i2c_gpio.I2cService(self.uc, {(0, 0x30): self.sensor})

    def run_command(self, entry, address, register, count, data=b''):
        record, buffer = 0x01000000, 0x01000100
        self.uc.mem_write(record, struct.pack('<BBBBIHHH', 0, address, 0x44, 0, buffer, register, count, 0))
        self.uc.mem_write(buffer, data.ljust(16, b'\0'))
        self.uc.reg_write(UC_ARM_REG_R0, record)
        self.uc.reg_write(UC_ARM_REG_LR, 0x02000000)
        self.uc.reg_write(UC_ARM_REG_PC, entry)
        (self.service.read if entry == i2c_gpio.READ_ENTRY else self.service.write)(self.uc, entry, 4, None)
        return self.uc.reg_read(UC_ARM_REG_R0), bytes(self.uc.mem_read(buffer, 4)), struct.unpack('<H', self.uc.mem_read(record + 0xc, 2))[0]

    def test_sensor_id_is_read(self):
        code, data, done = self.run_command(i2c_gpio.READ_ENTRY, 0x60, 0x0a, 2)
        self.assertEqual((code, data[:2], done), (0, bytes([0x96, 0x57]), 2))
        self.assertEqual(self.uc.reg_read(UC_ARM_REG_PC), 0x02000000)       # returned to the caller

    def test_register_write_is_stored(self):
        code, _, done = self.run_command(i2c_gpio.WRITE_ENTRY, 0x60, 0x12, 1, b'\x80')
        self.assertEqual((code, done, self.sensor.registers[0x12]), (0, 1, 0x80))

    def test_unknown_slave_does_not_acknowledge(self):
        code, _, done = self.run_command(i2c_gpio.READ_ENTRY, 0x90, 0x0a, 1)
        self.assertEqual((code, done), (i2c_gpio.ERROR_NO_ACK, 0))


class HeadsetJackTests(unittest.TestCase):
    def read_word(self, inserted):
        uc = machine(0x84000000)
        jack = gpio_inputs.HeadsetJack(uc, inserted)
        jack.read(uc, 16, 0x8400016c, 4, 0, None)
        return int.from_bytes(uc.mem_read(0x8400016c, 4), 'little')

    def test_not_inserted_sets_bit_5(self):
        self.assertTrue(self.read_word(False) & (1 << 5))

    def test_inserted_clears_bit_5(self):
        self.assertFalse(self.read_word(True) & (1 << 5))


class SdWriteTests(unittest.TestCase):
    def test_block_write_sets_the_completion_bits_the_driver_waits_for(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'card.img'
            image.write_bytes(bytes(1024 * 1024))
            uc = machine(0x61800000, 0x84000000)
            controller = mmc_controller.MmcController(mmc_card.SdCard(str(image)))
            controller.attach(uc)
            controller.card.state = mmc_card.TRAN
            controller.registers.update({mmc_controller.COMMAND: 0x58, mmc_controller.ARG_HIGH: 0, mmc_controller.ARG_LOW: 0x400, 0x20: 1})
            controller.send_command(0xd)                                  # CMD24 at byte 1024
            status = int.from_bytes(uc.mem_read(0x61800004, 4), 'little')
            controller.read(uc, 16, 0x61800004, 4, 0, None)
            status = int.from_bytes(uc.mem_read(0x61800004, 4), 'little')
            self.assertTrue(status & mmc_controller.TX_READY)             # bit 6: ready for data (polled at 0x3680c4)
            for word in range(256):
                controller.receive_word(0xab00 | word)
            status = int.from_bytes(uc.mem_read(0x61800004, 4), 'little')
            self.assertEqual(status & mmc_controller.WRITE_DONE, mmc_controller.WRITE_DONE)   # bits 11 and 12 (polled at 0x368276)
            controller.card.close()
            self.assertEqual(image.read_bytes()[1024:1028], bytes([0xab, 0x00, 0xab, 0x01]))


class NetworkTests(unittest.TestCase):
    def test_plmn_bytes_for_three_digit_mnc(self):
        self.assertEqual(netsim.plmn_bytes('222', '99'), bytes([2, 2, 2, 2, 9, 9, 0xf]))

    def test_signal_goes_through_the_report_queue(self):
        uc = machine(0x04f00000)
        network = netsim.Network.__new__(netsim.Network)
        network.signal_requests = []
        network.report_signal(85)
        self.assertEqual(network.signal_requests, [(85, 0x29, 0)])


if __name__ == '__main__':
    unittest.main()
