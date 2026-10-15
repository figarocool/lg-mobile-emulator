from pathlib import Path
import struct
import unittest
from inspect_nv import decode_nv2, parse_records, KEY

ROOT = Path(__file__).resolve().parents[1]

class NvTests(unittest.TestCase):
    def test_u310_record_layout(self):
        records = parse_records((ROOT/'firmware/u310.nvm').read_bytes())
        self.assertEqual(len(records), 380)
        self.assertIn(550, records)
        self.assertEqual(len(records[550][0]['payload']), 128)

    def test_donor_decode_and_roundtrip(self):
        header, body = decode_nv2((ROOT/'references/NV_U880_U890.nv2').read_bytes())
        self.assertEqual(header['model'], 'U890')
        self.assertEqual(header['count'], 417)
        records = parse_records(body)
        self.assertEqual(len(records), 408)
        self.assertEqual(sum(len(g) for g in records.values()), 417)
        self.assertEqual(len(records[848]), 2)
        self.assertEqual(header['systemtime'][0], 2006)

    def test_corrupted_count_rejected(self):
        plain = bytearray(32)
        struct.pack_into('<I', plain, 0, 2)
        struct.pack_into('<I', plain, 12, 1)
        encoded = b'RGNV'+bytes(((b^KEY[i%16])+KEY[i%16])&255 for i,b in enumerate(plain))
        with self.assertRaises(ValueError):
            decode_nv2(encoded)

if __name__ == '__main__':
    unittest.main()
