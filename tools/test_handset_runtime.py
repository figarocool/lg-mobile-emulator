"""Regression checks for model isolation and execution of decoded U880 code."""
import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Crypto.Cipher import AES
import handset_runtime
from decrypt_u880_code import PREFIX, LOAD
from emulator import run
from u880_machine import run as run_machine
import u310


class HandsetTests(unittest.TestCase):
    def fixture(self, folder):
        key = bytes(range(16))
        # Eight genuine self-branching vectors, a minimal valid image.
        plain = bytes(PREFIX)+struct.pack('<8I', *([0xeafffffe]*8))
        encoded = AES.new(key, AES.MODE_CBC, iv=bytes(16)).encrypt(plain)
        (folder/'firmware').mkdir()
        code = folder/'firmware'/'CODE.bin'
        code.write_bytes(encoded)
        (folder/'profile.json').write_text('{"profile_id":"u880-test"}')
        key_file = folder/'key.bin'
        key_file.write_bytes(key)
        spec = {'model': 'LG U880', 'version': 'test',
                'files': {'CODE': {'name': code.name, 'sha256': hashlib.sha256(encoded).hexdigest()}}}
        return spec, key_file, code

    def test_loads_and_runs_selected_ciphertext_without_changing_source(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            spec, key, code = self.fixture(folder)
            original = code.read_bytes()
            with patch.dict(handset_runtime.PROFILES, {'u880-test': spec}):
                result = handset_runtime.run_u880('u880-test', instance=folder, key_file=key, limit=12)
            self.assertEqual(code.read_bytes(), original)
            self.assertEqual(result['instructions'], 12)
            self.assertEqual(result['pc'], hex(LOAD))
            self.assertEqual(result['profile_id'], 'u880-test')
            self.assertFalse(result['boot_succeeded'])

    def test_wrong_key_and_modified_firmware_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            spec, key, code = self.fixture(folder)
            with patch.dict(handset_runtime.PROFILES, {'u880-test': spec}):
                key.write_bytes(bytes(16))
                with self.assertRaisesRegex(ValueError, 'Wrong key/format'):
                    handset_runtime.load_u880('u880-test', folder, key)
                code.write_bytes(code.read_bytes()+bytes(16))
                with self.assertRaisesRegex(ValueError, 'SHA-256'):
                    handset_runtime.load_u880('u880-test', folder, key)

    def test_wrong_instance_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder/'profile.json').write_text('{"profile_id":"u310-v10a-h3g"}')
            with self.assertRaisesRegex(ValueError, 'non corrisponde'):
                handset_runtime.resolve_instance('u880-v10b-h3g', folder)

    def test_strict_uninitialized_read_and_shadow_are_distinct(self):
        # Read one MMIO register, then loop. There is no fabricated register reply in strict mode.
        image = struct.pack('<4I', 0xe59f0004, 0xe5901000, 0xeafffffe, 0x80003404)
        strict = run_machine(image, 20)
        shadow = run_machine(image, 20, shadow=True)
        self.assertEqual(strict['accesses'][0]['address'], '0x80003404')
        self.assertEqual(strict['instructions'], 2)
        self.assertEqual(shadow['instructions'], 20)
        self.assertTrue(shadow['shadow_mmio'])
        self.assertFalse(shadow['boot_succeeded'])

    def test_strict_ram_read_does_not_silently_use_zero(self):
        image = struct.pack('<4I', 0xe59f0004, 0xe5901000, 0xeafffffe, 0x2000000)
        self.assertNotEqual(run_machine(image, 20)['stop'], 'instruction limit')
        self.assertEqual(run_machine(image, 20, zero_ram=True)['stop'], 'instruction limit')

    def test_missing_manager_stops_at_actual_guest_return(self):
        image = struct.pack('<2I', 0xe3e00000, 0xeafffffe)  # R0=-1, then loop
        result = run_machine(image, 20, manager_open_return=LOAD+4)
        self.assertFalse(result['phone_manager_open']['succeeded'])
        self.assertEqual(result['phone_manager_open']['handle'], '0xffffffff')
        self.assertIn('PhoneMngr.pxo missing', result['stop'])

    def test_timer_interrupt_uses_u880_vector_base(self):
        image = bytearray(0x98)
        struct.pack_into('<I', image, 0, 0xea00000e)  # reset -> +0x40
        struct.pack_into('<I', image, 0x18, 0xea000018)  # IRQ -> +0x80
        struct.pack_into('<10I', image, 0x40,
                         0xe59f0018, 0xe3a01001, 0xe5801000, 0xe59f0010,
                         0xe5801000, 0xe321f013, 0xeafffffe, 0xe1a00000,
                         0x80003450, 0x84000250)
        struct.pack_into('<6I', image, 0x80,
                         0xe59f000c, 0xe3a01001, 0xe5801000, 0xe25ef004,
                         0xe1a00000, 0x84000248)
        result = run_machine(bytes(image), 20000, shadow=True, zero_ram=True, irq=True)
        self.assertGreater(result['timer_irq']['delivered'], 0)
        self.assertGreater(result['timer_irq']['acks'], 0)
        self.assertEqual(result['timer_irq']['vector_base'], '0xc0000')
        fast = run_machine(bytes(image), 400000, shadow=True, zero_ram=True, irq=True, fast=True)
        self.assertGreater(fast['timer_irq']['delivered'], 0)
        self.assertGreater(fast['timer_irq']['acks'], 0)

    def test_u880_checkpoint_continues_cpu_and_rejects_different_firmware(self):
        image = struct.pack('<2I', 0xe2811001, 0xeafffffd)  # Increment R1, loop.
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp)/'u880.zip'
            first = run_machine(image, 12, zero_ram=True, save_checkpoint=snapshot)
            second = run_machine(image, 12, zero_ram=True, resume=snapshot)
            self.assertGreater(int(second['registers']['r1'], 16),
                               int(first['registers']['r1'], 16))
            self.assertEqual(second['instructions_before_resume'], 12)
            with self.assertRaisesRegex(ValueError, 'identical Unicorn version'):
                run_machine(image+b'\x00'*4, 12, zero_ram=True, resume=snapshot)

    def test_fast_u880_preserves_cpu_result_and_execution_guard(self):
        image = struct.pack('<2I', 0xe2811001, 0xeafffffd)
        slow = run_machine(image, 120)
        fast = run_machine(image, 120, fast=True)
        self.assertEqual(slow['registers'], fast['registers'])
        self.assertEqual(slow['pc'], fast['pc'])
        self.assertEqual(fast['instructions'], 120)
        jump = struct.pack('<2I', 0xe51ff004, 0x2000000)
        stopped = run_machine(jump, 120, zero_ram=True, fast=True)
        self.assertEqual(stopped['stop'], 'execution outside decoded code')

    def test_u310_services_cannot_be_attached_to_u880(self):
        with self.assertRaisesRegex(ValueError, 'mdsp_management'):
            run('amss', mdsp_management=True, profile='u880-v10b-h3g')
        with self.assertRaisesRegex(ValueError, 'flip'):
            run('amss', flip=False, profile='u880-v10b-h3g')
        with self.assertRaisesRegex(ValueError, 'opzioni U880'):
            run('amss', zero_ram=True)

    def test_default_launcher_keeps_u310_window(self):
        with patch.object(u310.subprocess, 'call', return_value=0) as call:
            self.assertEqual(u310.main(['run']), 0)
        self.assertEqual(Path(call.call_args.args[0][1]).name, 'window.py')

    def test_u880_launcher_uses_common_emulator(self):
        with patch.object(u310.subprocess, 'call', return_value=0) as call:
            self.assertEqual(u310.main(['run', '--profile', 'u880-v10a-h3g', '--', '--limit', '12']), 0)
        command = call.call_args.args[0]
        self.assertEqual(Path(command[1]).name, 'emulator.py')
        self.assertIn('u880-v10a-h3g', command)
        self.assertEqual(command[-2:], ['--limit', '12'])


if __name__ == '__main__':
    unittest.main()
