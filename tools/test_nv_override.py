import tempfile
import unittest
from pathlib import Path

import nv_override
import settings


class IdentityTests(unittest.TestCase):
    def test_encoding_matches_the_firmwares_own_default_imei(self):
        # The firmware compares the stored identity with 0a 40 04 10 25 20 00 00 for "Default IMEI 00440015202000".
        default = bytes([8, 0x0a, 0x40, 0x04, 0x10, 0x25, 0x20, 0x00, 0x00])
        digits14 = '00440015202000'
        self.assertEqual(nv_override.imei_nv(digits14)[:8], default[:8])

    def test_check_digit_is_added_and_verified(self):
        self.assertEqual(nv_override.normalize_imei('35693803564380'), '356938035643809')
        self.assertEqual(nv_override.normalize_imei('356938035643809'), '356938035643809')
        with self.assertRaises(ValueError):
            nv_override.normalize_imei('356938035643808')
        with self.assertRaises(ValueError):
            nv_override.normalize_imei('1234')
        with self.assertRaises(ValueError):
            nv_override.normalize_imei('35693803564380a')

    def test_imei_layout_for_a_known_number(self):
        data = nv_override.imei_nv('356938035643809')
        self.assertEqual(len(data), 9)
        self.assertEqual(data[0], 8)
        self.assertEqual(data[1], 0x3a)          # first digit 3, type nibble 0xa
        self.assertEqual(data[2], 0x65)          # digits 2 and 3: 5, 6

    def test_bluetooth_address_is_stored_least_significant_byte_first(self):
        self.assertEqual(nv_override.bd_addr_nv('00:1B:DC:0F:A3:5E'), bytes([0x5e, 0xa3, 0x0f, 0xdc, 0x1b, 0x00]))
        for bad in ('00:1B:DC:0F:A3', '00:1B:DC:0F:A3:5E:11', 'zz:1B:DC:0F:A3:5E', '001BDC0FA35'):
            with self.assertRaises(ValueError):
                nv_override.parse_bd_addr(bad)

    def test_settings_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sub' / 's.json'
            self.assertEqual(settings.load(path), settings.DEFAULTS)
            custom = dict(settings.DEFAULTS, imei='490154203237518', cpu_mhz=60.0)
            settings.save(custom, path)
            self.assertEqual(settings.load(path), custom)
            settings.validate(custom)
            with self.assertRaises(ValueError):
                settings.validate(dict(custom, bt_addr='nonsense'))


if __name__ == '__main__':
    unittest.main()
