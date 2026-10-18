import unittest
from usim_card import UsimCard, imsi_bytes, bcd_swap, USIM_AID


def apdu(card, header, data=b''):
    """Send a full APDU byte by byte, return (procedure/data bytes, status)."""
    out = b''
    for byte in header:
        out = card.receive(byte)
    if data:
        # after the header the card answered with the procedure byte; then the data goes out
        assert out == bytes([header[1]]), out.hex()
        for byte in data:
            out = card.receive(byte)
    return out


class CardTests(unittest.TestCase):
    def setUp(self):
        self.card = UsimCard('222990000000001')

    def test_imsi_encoding_has_parity_nibble_and_length(self):
        # 15 digits => parity nibble 9 first: 9 2 2 2 9 9 0..0 1, each pair nibble-swapped.
        self.assertEqual(imsi_bytes('222990000000001'), bytes.fromhex('0829229900000000' + '10'))
        self.assertEqual(bcd_swap('12'), b'\x21')
        self.assertEqual(bcd_swap('123'), bytes([0x21, 0xf3]))

    def test_pps_is_echoed_when_complete(self):
        out = b''
        for byte in (0xff, 0x10, 0x96, 0xff ^ 0x10 ^ 0x96):
            out = self.card.receive(byte)
        self.assertEqual(out, bytes([0xff, 0x10, 0x96, 0x79]))

    def test_select_mf_returns_61_then_get_response_gives_fcp(self):
        out = apdu(self.card, bytes.fromhex('00a4000402'), bytes.fromhex('3f00'))
        self.assertEqual(out[0] , 0x61)
        length = out[1]
        resp = apdu(self.card, bytes([0x00, 0xc0, 0x00, 0x00, length]))
        self.assertEqual(resp[0], 0xc0)
        fcp = resp[1:-2]
        self.assertEqual(fcp[0], 0x62)
        self.assertEqual(fcp[1], len(fcp) - 2)
        self.assertEqual(resp[-2:], b'\x90\x00')

    def test_read_iccid_binary(self):
        apdu(self.card, bytes.fromhex('00a4000402'), bytes.fromhex('2fe2'))
        resp = apdu(self.card, bytes.fromhex('00b000000a'))
        self.assertEqual(resp[0], 0xb0)
        self.assertEqual(len(resp), 1 + 10 + 2)

    def test_select_usim_by_aid_then_read_imsi(self):
        out = apdu(self.card, bytes([0x00, 0xa4, 0x04, 0x04, len(USIM_AID)]), USIM_AID)
        self.assertEqual(out[0], 0x61)
        apdu(self.card, bytes.fromhex('00a4000402'), bytes.fromhex('6f07'))
        resp = apdu(self.card, bytes.fromhex('00b0000009'))
        self.assertEqual(resp[1:-2], imsi_bytes('222990000000001'))

    def test_read_imsi_le_zero_reports_exact_length_before_retry(self):
        self.card.strict_read_length = True
        apdu(self.card, bytes([0, 0xa4, 4, 4, len(USIM_AID)]), USIM_AID)
        apdu(self.card, bytes.fromhex('00a4000402'), bytes.fromhex('6f07'))
        self.assertEqual(apdu(self.card, bytes.fromhex('00b0000000')), bytes.fromhex('6c09'))
        self.assertEqual(apdu(self.card, bytes.fromhex('00b0000009')),
                         b'\xb0'+imsi_bytes('222990000000001')+b'\x90\x00')

    def test_absolute_ef_select_sets_parent_for_following_relative_select(self):
        out=apdu(self.card,bytes.fromhex('00a4080404'),bytes.fromhex('7fff6fad'))
        self.assertEqual(out[0],0x61)
        self.assertEqual(self.card.current_df.fid,0x7fff)
        out=apdu(self.card,bytes.fromhex('00a4000402'),bytes.fromhex('6f07'))
        self.assertEqual(out[0],0x61)
        self.assertEqual(apdu(self.card,bytes.fromhex('00b0000009'))[1:-2],imsi_bytes('222990000000001'))

    def test_unknown_file_is_6a82_and_unknown_instruction_6d00(self):
        out = apdu(self.card, bytes.fromhex('00a4000402'), bytes.fromhex('1234'))
        self.assertEqual(out, bytes([0x6a, 0x82]))
        self.assertEqual(apdu(self.card, bytes.fromhex('0099000000')), bytes([0x6d, 0x00]))

    def test_gsm_class_is_rejected_so_the_driver_uses_uicc_commands(self):
        out = apdu(self.card, bytes.fromhex('a0a4000002'), bytes.fromhex('3f00'))
        self.assertEqual(out, bytes([0x6e, 0x00]))

    def test_read_record_wrong_length_reports_6c(self):
        apdu(self.card, bytes.fromhex('00a4000402'), bytes.fromhex('2f00'))
        out = apdu(self.card, bytes.fromhex('00b2010405'))
        self.assertEqual(out, bytes([0x6c, 0x21]))


if __name__ == '__main__':
    unittest.main()


class ResetTests(unittest.TestCase):
    def test_reset_clears_partial_command_and_selection(self):
        card = UsimCard()
        apdu(card, bytes.fromhex('00a4000402'), bytes.fromhex('2fe2'))
        card.receive(0x00)
        card.receive(0xb0)  # half a header
        card.reset()
        self.assertEqual(len(card.buffer), 0)
        self.assertIs(card.current_ef, None)
        self.assertIs(card.current_df, card.mf)


class DataStartingWithFFTests(unittest.TestCase):
    def test_command_data_beginning_with_ff_is_not_taken_for_pps(self):
        card = UsimCard()
        data = bytes([0xff, 0xff, 0xff, 0xff, 0x7f, 0x0f] + [0] * 14)
        out = apdu(card, bytes.fromhex('8010000014'), data)
        self.assertEqual(out, bytes([0x90, 0x00]))
        self.assertEqual(card.pps, [])


class SearchTests(unittest.TestCase):
    def test_search_ef_dir_for_usim_aid_prefix(self):
        card = UsimCard()
        apdu(card, bytes.fromhex('00a4080402'), bytes.fromhex('2f00'))
        pattern = bytes([0x4f, 0x0c]) + USIM_AID[:7]
        out = apdu(card, bytes([0x00, 0xa2, 0x01, 0x06, len(pattern)]), pattern)
        self.assertEqual(out, bytes([0x61, 0x01]))
        self.assertEqual(apdu(card, bytes.fromhex('00c0000001')), bytes([0xc0, 0x01, 0x90, 0x00]))

    def test_search_without_match_is_6a83(self):
        card = UsimCard()
        apdu(card, bytes.fromhex('00a4080402'), bytes.fromhex('2f00'))
        out = apdu(card, bytes.fromhex('00a2010602'), bytes.fromhex('beef'))
        self.assertEqual(out, bytes([0x6a, 0x83]))


class EnhancedSearchTests(unittest.TestCase):
    def test_enhanced_search_from_offset_4_finds_the_aid(self):
        card = UsimCard()
        apdu(card, bytes.fromhex('00a4080402'), bytes.fromhex('2f00'))
        data = bytes([0x04, 0x04]) + USIM_AID[:7]
        out = apdu(card, bytes([0x00, 0xa2, 0x01, 0x06, len(data)]), data)
        self.assertEqual(out, bytes([0x61, 0x01]))

    def test_enhanced_search_at_wrong_offset_finds_nothing(self):
        card = UsimCard()
        apdu(card, bytes.fromhex('00a4080402'), bytes.fromhex('2f00'))
        data = bytes([0x04, 0x05]) + USIM_AID[:7]
        self.assertEqual(apdu(card, bytes([0x00, 0xa2, 0x01, 0x06, len(data)]), data), bytes([0x6a, 0x83]))


class PinTests(unittest.TestCase):
    def test_verify_query_and_unblock_query(self):
        card = UsimCard()
        self.assertEqual(apdu(card, bytes.fromhex('0020000100')), bytes([0x63, 0xc3]))
        self.assertEqual(apdu(card, bytes.fromhex('002c000100')), bytes([0x63, 0xca]))


class PinPromptTests(unittest.TestCase):
    def test_card_with_disabled_pin_still_reports_remaining_attempts(self):
        self.assertEqual(apdu(UsimCard(pin_prompt=False), bytes.fromhex('0020000100')), bytes([0x63, 0xc3]))

    def test_prompting_card_needs_the_pin_and_reset_forgets_it(self):
        card = UsimCard(pin_prompt=True)
        self.assertEqual(apdu(card, bytes.fromhex('0020000100')), bytes([0x63, 0xc3]))
        data = b'0000' + b'\xff' * 4
        self.assertEqual(apdu(card, bytes.fromhex('0020000108'), data), bytes([0x90, 0x00]))
        self.assertEqual(apdu(card, bytes.fromhex('0020000100')), bytes([0x90, 0x00]))
        card.reset()
        self.assertEqual(apdu(card, bytes.fromhex('0020000100')), bytes([0x63, 0xc3]))


class SnapshotTests(unittest.TestCase):
    def test_snapshot_round_trip_keeps_selection_and_pin_state(self):
        card = UsimCard(pin_prompt=True)
        apdu(card, bytes.fromhex('00a4080402'), bytes.fromhex('2fe2'))
        data = b'0000' + b'\xff' * 4
        apdu(card, bytes.fromhex('0020000108'), data)
        other = UsimCard(pin_prompt=True)
        other.load(card.snapshot())
        self.assertEqual(other.current_ef.fid, 0x2fe2)
        self.assertTrue(other.pin_verified)
