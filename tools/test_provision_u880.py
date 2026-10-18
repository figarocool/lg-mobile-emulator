"""CODE input format regression tests using synthetic ARM vectors only."""
import hashlib
import struct
import unittest
from unittest.mock import patch
from Crypto.Cipher import AES
import provision_u880 as installer
from decrypt_u880_code import PREFIX
class CodeInputs(unittest.TestCase):
    def setUp(self):
        self.amss=struct.pack('<8I',*([0xeafffffe]*8));self.plain=bytes(PREFIX)+self.amss
        self.key=bytes(range(16));self.encrypted=AES.new(self.key,AES.MODE_CBC,iv=bytes(16)).encrypt(self.plain)
        self.patches=[patch.object(installer,'AMSS_SHA',hashlib.sha256(self.amss).hexdigest()),patch.object(installer,'PROFILES',{'u880-v10b-h3g':{'files':{'CODE':{'sha256':hashlib.sha256(self.encrypted).hexdigest()}}}})]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def test_plain_amss_and_prefixed_code_need_no_key(self):
        self.assertEqual(installer.decode_code(self.amss),(self.amss,'plain-amss'))
        self.assertEqual(installer.decode_code(self.plain),(self.amss,'plain-code'))
    def test_encrypted_code_with_local_key(self):
        self.assertEqual(installer.decode_code(self.encrypted,self.key),(self.amss,'encrypted-code'))
    def test_missing_and_wrong_key_rejected(self):
        for key in (None,bytes(16),b'short'):
            with self.subTest(key_length=0 if key is None else len(key)):
                with self.assertRaises(ValueError):installer.decode_code(self.encrypted,key)
    def test_unknown_or_modified_code_rejected(self):
        for data in (b'',self.amss[:-1],self.encrypted[:-1],b'X'+self.amss[1:]):
            with self.assertRaises(ValueError):installer.decode_code(data,self.key)
if __name__=='__main__':unittest.main()
