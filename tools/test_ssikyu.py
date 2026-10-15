import struct
import unittest
from ssikyu_crypto import CryptoProbe
from ssikyu_fixture import initialize, MAGIC
from msm6250_nand import NandController

class SsikyuTests(unittest.TestCase):
    def test_original_crypto_roundtrip(self):
        probe = CryptoProbe()
        original = bytes(range(256))*2
        cipher = probe.transform(original, encrypt=True)
        self.assertNotEqual(cipher, original)
        self.assertEqual(probe.transform(cipher), original)

    def test_synthetic_metadata_and_no_overwrite(self):
        nand = NandController()
        report = initialize(nand)
        self.assertFalse(report['original_phone_nv_data_recovered'])
        probe = CryptoProbe()
        begin = 27 * nand.BLOCK
        for index, magic in enumerate(MAGIC):
            page = bytes(nand.storage[begin+index*512:begin+(index+1)*512])
            plain = probe.transform(page)
            self.assertEqual(struct.unpack_from('<III', plain), (*magic, 1))
        with self.assertRaises(ValueError):
            initialize(nand)

    def test_physical_dump_not_modified_by_fixture(self):
        nand = NandController(b'\xff'*NandController.SIZE)
        with self.assertRaises(ValueError):
            initialize(nand)

if __name__ == '__main__':
    unittest.main()
