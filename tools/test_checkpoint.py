"""Check real instruction continuity and device state across snapshots."""
import tempfile
import unittest
from pathlib import Path
from emulator import run

class SnapshotTests(unittest.TestCase):
    def test_arm_instruction_continuity(self):
        expected = run(limit=100)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'state.zip'
            prefix = run(limit=5, save_checkpoint=path)
            result = run(limit=100, resume=path)
        self.assertEqual(prefix['instructions']+result['instructions'], expected['instructions'])
        self.assertEqual(result['pc'], expected['pc'])
        self.assertEqual(result['registers'], expected['registers'])
        self.assertEqual(result['last_unmapped'], expected['last_unmapped'])

    def test_nand_discovery_continuity(self):
        expected = run('nand-init', True, 10000, True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'state.zip'
            run('nand-init', True, 130, True, save_checkpoint=path)
            result = run('nand-init', True, 10000, True, resume=path)
        self.assertEqual(result['nand'], expected['nand'])
        self.assertEqual(result['device_structure'], expected['device_structure'])
        self.assertEqual(result['return_value'], expected['return_value'])

    def test_different_configuration_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'state.zip'
            run(limit=5, save_checkpoint=path)
            with self.assertRaises(ValueError):
                run(shadow=True, resume=path)

if __name__ == '__main__':
    unittest.main()
