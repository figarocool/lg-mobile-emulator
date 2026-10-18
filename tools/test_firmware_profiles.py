import hashlib
import tempfile
import unittest
from pathlib import Path

import firmware_profiles


class FirmwareProfileDetectionTests(unittest.TestCase):
    def setUp(self):
        self.original = firmware_profiles.PROFILES
        self.payloads = {f'{prefix}-{role}': (f'{prefix}-{role}'.encode() * 500)
                         for prefix in ('a', 'b') for role in ('CODE', 'MEDIA', 'MODULE')}
        self.profiles = {
            'model-a': {'model': 'Model A', 'version': 'A1', 'bootable': True,
                        'files': {role: {'name': f'a-{role}.bin', 'sha256': hashlib.sha256(self.payloads[f'a-{role}']).hexdigest()}
                                  for role in ('CODE', 'MEDIA', 'MODULE')}},
            'model-b': {'model': 'Model B', 'version': 'B1', 'bootable': False,
                        'files': {role: {'name': f'b-{role}.bin', 'sha256': hashlib.sha256(self.payloads[f'b-{role}']).hexdigest()}
                                  for role in ('CODE', 'MEDIA', 'MODULE')}},
        }
        firmware_profiles.PROFILES = self.profiles

    def tearDown(self):
        firmware_profiles.PROFILES = self.original

    def test_identifies_complete_set_by_content_when_names_are_changed(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for role in ('CODE', 'MEDIA', 'MODULE'):
                (folder / f'renamed-{role}').write_bytes(self.payloads[f'b-{role}'])
            profile_id, files, problems = firmware_profiles.identify(folder)
        self.assertEqual(profile_id, 'model-b')
        self.assertEqual(set(files), {'CODE', 'MEDIA', 'MODULE'})
        self.assertEqual(problems, [])

    def test_partial_firmware_reports_missing_roles(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'code').write_bytes(self.payloads['a-CODE'])
            profile_id, _files, problems = firmware_profiles.identify(folder)
        self.assertIsNone(profile_id)
        self.assertTrue(any('MEDIA' in problem and 'MODULE' in problem for problem in problems))

    def test_two_complete_profiles_must_be_separated(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for prefix in ('a', 'b'):
                for role in ('CODE', 'MEDIA', 'MODULE'):
                    (folder / f'{prefix}-{role}').write_bytes(self.payloads[f'{prefix}-{role}'])
            profile_id, _files, problems = firmware_profiles.identify(folder)
        self.assertIsNone(profile_id)
        self.assertTrue(any('più firmware completi' in problem for problem in problems))

    def test_u880_v10a_profile_includes_boot_stages_but_is_not_bootable(self):
        profile = self.original['u880-v10a-h3g']
        self.assertEqual(set(profile['files']),
                         {'BOOTLOADER', 'BOOTSHELL', 'CODE', 'MEDIA', 'MODULE'})
        self.assertFalse(profile['bootable'])
        self.assertEqual(profile['code_decoder']['load_address'], 0xc0000)
        self.assertIn('startup', profile['boot_blocker'])


if __name__ == '__main__':
    unittest.main()
