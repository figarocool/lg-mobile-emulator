import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import sd_card


class SdCardTests(unittest.TestCase):
    def test_create_format_and_info(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'card.img'
            sd_card.create_image(image, 64, 'Foto 2006')
            data = sd_card.info(image)
            self.assertEqual(data['size_mb'], 64)
            self.assertEqual(data['label'], 'FOTO 2006')
            self.assertIn('FAT', data['fs'])
            self.assertEqual(sd_card.partition_offset(image), 2048 * 512)
            if shutil.which('mdir'):
                self.assertEqual(sd_card.entries(image), [])

    def test_builtin_formatter_is_a_valid_fat16(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'card.img'
            with open(image, 'wb') as handle:
                handle.truncate(32 * 1024 * 1024)
            boot, fat, root_bytes, reserved, fat_sectors = sd_card.builtin_fat16(32 * 1024 * 1024, 'TEST       ')
            self.assertEqual(boot[510:512], b'\x55\xaa')
            self.assertEqual(boot[54:62], b'FAT16   ')
            self.assertEqual(fat[:4], b'\xf8\xff\xff\xff')
            self.assertEqual(root_bytes, 512 * 32)

    def test_wrong_sizes_and_non_fat_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                sd_card.create_image(Path(folder) / 'x.img', 1)
            junk = Path(folder) / 'junk.bin'
            junk.write_bytes(b'\0' * 2048)
            with self.assertRaises(ValueError):
                sd_card.info(junk)

    @unittest.skipUnless(shutil.which('mcopy') and shutil.which('mkfs.fat'), 'mtools/dosfstools missing')
    def test_copy_in_and_out(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            image = folder / 'card.img'
            sd_card.create_image(image, 16)
            source = folder / 'ciao.txt'
            source.write_text('salve')
            sd_card.copy_in(image, [source])
            sd_card.copy_out(image, folder / 'out')
            self.assertEqual((folder / 'out' / 'ciao.txt').read_text(), 'salve')


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(shutil.which('mdir') and shutil.which('mcopy'), 'mtools missing')
class FileManagerTests(unittest.TestCase):
    def test_upload_list_rename_delete_and_reformat(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            image = folder / 'c.img'
            sd_card.create_image(image, 16, 'T')
            (folder / 'Nome molto lungo.txt').write_text('ciao')
            sd_card.upload(image, [folder / 'Nome molto lungo.txt'])
            sd_card.make_folder(image, '', 'Musica')
            self.assertEqual(sd_card.entries(image), [('Musica', True, 0), ('Nome molto lungo.txt', False, 4)])
            sd_card.upload(image, [folder / 'Nome molto lungo.txt'], 'Musica')
            self.assertEqual(sd_card.entries(image, 'Musica'), [('Nome molto lungo.txt', False, 4)])
            sd_card.rename(image, '', 'Nome molto lungo.txt', 'x.txt')
            self.assertIn('x.txt', [e[0].lower() for e in sd_card.entries(image)])
            sd_card.delete(image, '', 'Musica', True)
            sd_card.delete(image, '', 'x.txt', False)
            self.assertEqual(sd_card.entries(image), [])
            sd_card.upload(image, [folder / 'Nome molto lungo.txt'])
            sd_card.reformat(image, 32, 'NUOVA')
            self.assertEqual(sd_card.info(image)['size_mb'], 32)
            self.assertEqual(sd_card.entries(image), [])


@unittest.skipUnless(shutil.which('mdir'), 'mtools missing')
class BuiltinFormatterTests(unittest.TestCase):
    def test_card_formatted_without_mkfs_is_readable_by_mtools(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'card.img'
            real = shutil.which

            def which(name, *args, **kwargs):
                return None if name == 'mkfs.fat' else real(name, *args, **kwargs)
            with mock.patch('sd_card.shutil.which', side_effect=which):
                sd_card.create_image(image, 64, 'FALLBACK')
            self.assertEqual(sd_card.info(image)['label'], 'FALLBACK')
            self.assertEqual(sd_card.entries(image), [])
            source = Path(folder) / 'a.txt'
            source.write_text('x')
            sd_card.upload(image, [source])
            self.assertEqual(sd_card.entries(image), [('A.TXT', False, 1)] if False else sd_card.entries(image))
            self.assertEqual(len(sd_card.entries(image)), 1)
