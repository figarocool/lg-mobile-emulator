import json
import tempfile
import unittest
from pathlib import Path

import sim_profile
from usim_card import UsimCard


def apdu(card, hex_header, data=b''):
    out = bytearray()
    for byte in bytes.fromhex(hex_header):
        out += card.receive(byte)
    if data:
        for byte in data:
            out += card.receive(byte)
    return bytes(out)


class MsisdnTests(unittest.TestCase):
    def test_international_number_roundtrip(self):
        record = sim_profile.msisdn_record('+393331234567', 'Il mio numero')
        self.assertEqual(len(record), 28)
        self.assertEqual(record[14], 7)                # 6 BCD bytes + 1 for TON/NPI
        self.assertEqual(record[15], 0x91)             # international
        self.assertEqual(sim_profile.parse_msisdn(record), ('+393331234567', 'Il mio numero'))

    def test_national_number_without_plus(self):
        self.assertEqual(sim_profile.parse_msisdn(sim_profile.msisdn_record('3331234567', 'x')), ('3331234567', 'x'))

    def test_validation_messages(self):
        profile = dict(sim_profile.DEFAULTS, name='t')
        sim_profile.validate(profile)
        for key, value in (('imsi', '123'), ('msisdn', 'abc'), ('pin', '12'), ('puk', '1'), ('iccid', '1')):
            with self.assertRaises(ValueError):
                sim_profile.validate(dict(profile, **{key: value}))


class ProfileFileTests(unittest.TestCase):
    def test_save_load_and_list(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = dict(sim_profile.DEFAULTS, name='Lavoro', msisdn='+393401112223')
            sim_profile.save(profile, folder)
            self.assertEqual(sim_profile.load('Lavoro', folder)['msisdn'], '+393401112223')
            self.assertIn('Lavoro', sim_profile.list_names(folder))


class CardWritesPersistTests(unittest.TestCase):
    def test_phone_writes_survive_a_new_card_object(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'sim.state.json'
            card = UsimCard(pin_prompt=False, profile=dict(sim_profile.DEFAULTS), state_path=state)
            # SELECT MF/DF telecom/EF_ADN by path, UPDATE RECORD 1
            apdu(card, '00a4080404', bytes.fromhex('7f106f3a'))
            entry = bytes.fromhex('4d6172696f') + b'\xff' * 9 + bytes.fromhex('07915333000000f0ffffffffffffff')[:14]
            apdu(card, '00dc01041c', entry)
            self.assertTrue(state.exists())
            again = UsimCard(pin_prompt=False, profile=dict(sim_profile.DEFAULTS), state_path=state)
            adn = again.find_by_fid(0x6f3a)
            self.assertEqual(bytes(adn.records[0][:5]), bytes.fromhex('4d6172696f'))

    def test_card_exposes_the_profile_number_and_identity(self):
        profile = dict(sim_profile.DEFAULTS, msisdn='+393401112223', imsi='222990000000042')
        card = UsimCard(pin_prompt=False, profile=profile)
        msisdn = card.find_by_fid(0x6f40)
        self.assertEqual(sim_profile.parse_msisdn(bytes(msisdn.records[0]))[0], '+393401112223')
        self.assertEqual(card.imsi, '222990000000042')


if __name__ == '__main__':
    unittest.main()
