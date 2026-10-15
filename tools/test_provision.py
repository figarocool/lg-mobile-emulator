import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

import firmware_manifest as manifest


class FirmwareDetectionTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: dict(v) for k, v in {**manifest.REQUIRED}.items()}

    def tearDown(self):
        for key, value in self.saved.items():
            manifest.REQUIRED[key] = value

    def test_missing_files_are_reported_by_role(self):
        with tempfile.TemporaryDirectory() as folder:
            found, problems = manifest.find(folder)
            self.assertEqual(found, {})
            self.assertEqual(len(problems), 3)
            self.assertTrue(any('CODE' in p for p in problems))

    def test_files_are_recognised_by_content_not_by_name(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for role in manifest.REQUIRED:
                data = (role * 400).encode()
                (folder / f'{role.lower()}.renamed').write_bytes(data)
                manifest.REQUIRED[role]['sha256'] = manifest.hashlib.sha256(data).hexdigest()
            found, problems = manifest.find(folder)
            self.assertEqual(problems, [])
            self.assertEqual(set(found), {'CODE', 'MEDIA', 'MODULE'})

    def test_similar_name_with_other_content_gets_a_hint(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'U310-CODE-other.BIN').write_bytes(b'x' * 2000)
            _found, problems = manifest.find(folder)
            self.assertTrue(any('contenuto diverso' in p for p in problems))


class NandStateTests(unittest.TestCase):
    def test_saved_flash_has_the_cold_boot_format_and_keeps_a_backup(self):
        import emulator
        controller = SimpleNamespace(storage=bytearray(b'\x01' * 64), spare=bytearray(b'\x02' * 8), synthetic=True,
                                     address=1, config=2, status=0, pending=0, spare_word=3, direct_command=0,
                                     direct_status_reads=0, factory_fixture=None)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'phone.zip'
            emulator.write_nand_state(path, controller)
            controller.storage[0] = 9
            emulator.write_nand_state(path, controller)
            with zipfile.ZipFile(path) as z:
                self.assertEqual(z.read('nand.bin')[0], 9)
                self.assertEqual(z.read('nand_spare.bin'), b'\x02' * 8)
                self.assertTrue(json.loads(z.read('metadata.json'))['nand']['synthetic'])
            with zipfile.ZipFile(path.with_suffix('.bak')) as z:
                self.assertEqual(z.read('nand.bin')[0], 1)


if __name__ == '__main__':
    unittest.main()


class UninstallTests(unittest.TestCase):
    def test_uninstall_removes_the_phone_but_not_sims_or_cards(self):
        import provision
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            saved = (provision.ROOT, provision.DATA, provision.PHONE, provision.FACTORY)
            try:
                provision.ROOT, provision.DATA = root, root / 'data'
                provision.PHONE, provision.FACTORY = provision.DATA / 'phone.zip', provision.DATA / 'factory.zip'
                (root / 'firmware').mkdir()
                (root / 'extracted' / 'MEDIA').mkdir(parents=True)
                provision.DATA.mkdir()
                for path in (provision.PHONE, provision.FACTORY, provision.DATA / 'install.json', root / 'firmware' / 'a.bin'):
                    path.write_bytes(b'x')
                card = root / 'card.img'
                card.write_bytes(b'x')
                messages = []
                provision.uninstall(messages.append)
                self.assertFalse(provision.PHONE.exists() or provision.FACTORY.exists())
                self.assertFalse((root / 'firmware').exists() or (root / 'extracted').exists())
                self.assertTrue(card.exists())
                self.assertTrue(messages)
            finally:
                provision.ROOT, provision.DATA, provision.PHONE, provision.FACTORY = saved
