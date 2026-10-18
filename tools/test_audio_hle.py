import unittest
import tempfile
from pathlib import Path
import numpy as np
from audio_hle import tone_frequencies, render, render_nes_apu, RATE, AudioOutput


def dominant(samples, count=2):
    data = np.frombuffer(samples, dtype='<i2').astype(float)
    spectrum = np.abs(np.fft.rfft(data * np.hanning(len(data))))
    peaks = np.argsort(spectrum)[-count:]
    return sorted(round(p * RATE / len(data)) for p in peaks)


class ToneTests(unittest.TestCase):
    def test_observed_key_tone_ids_map_to_dtmf(self):
        self.assertEqual(tone_frequencies(1001), (941, 1336))   # '0'
        self.assertEqual(tone_frequencies(1002), (697, 1209))   # '1'
        self.assertEqual(tone_frequencies(1006), (770, 1336))   # '5'
        self.assertEqual(tone_frequencies(1010), (852, 1477))   # '9'
        self.assertEqual(tone_frequencies(1011), (941, 1209))   # '*'
        self.assertEqual(tone_frequencies(1012), (941, 1477))   # '#'

    def test_other_ids_are_not_key_tones(self):
        self.assertIsNone(tone_frequencies(1000))
        self.assertIsNone(tone_frequencies(1013))
        self.assertIsNone(tone_frequencies(5))

    def test_rendered_tone_has_the_two_frequencies(self):
        samples = render((770, 1336), 0, RATE // 2, 1.0)
        found = dominant(samples)
        self.assertTrue(all(abs(a - b) <= 4 for a, b in zip(found, (770, 1336))), found)

    def test_volume_scales_amplitude(self):
        loud = np.abs(np.frombuffer(render((1000,), 0, 800, 1.0), dtype='<i2')).max()
        quiet = np.abs(np.frombuffer(render((1000,), 0, 800, 0.25), dtype='<i2')).max()
        self.assertLess(quiet, loud * 0.3)

    def test_phase_is_continuous_across_chunks(self):
        whole = render((697, 1209), 0, 640)
        parts = render((697, 1209), 0, 320) + render((697, 1209), 320, 320)
        self.assertEqual(whole, parts)

    def test_nes_pulse_registers_produce_the_expected_pitch(self):
        regs = bytearray(24)
        regs[0], regs[2], regs[3], regs[0x15] = 0xbf, 111, 0, 1
        found = dominant(render_nes_apu(regs, 0, RATE // 4), count=1)[0]
        self.assertLessEqual(abs(found - 1001), 5, found)

    def test_disabled_nes_apu_is_silent(self):
        self.assertEqual(render_nes_apu(bytes(24), 0, 320), bytes(640))


class OutputTests(unittest.TestCase):
    def test_output_without_audio_tools_does_not_crash(self):
        out = AudioOutput()
        out.start_tone((697, 1209), 0.5)
        out.stop_tone()
        self.assertEqual(out.tones_started, 1)
        out.close()

    def test_nes_bridge_translates_live_controller_state(self):
        class GuestMemory:
            def __init__(self, base):
                self.base, self.data = base, bytearray(64)
            def mem_read(self, address, size):
                start = address - self.base
                return self.data[start:start + size]
            def mem_write(self, address, data):
                start = address - self.base
                self.data[start:start + len(data)] = data

        out = AudioOutput()
        base = 0x2000
        guest = GuestMemory(base)
        out.nes_apu_bridge = base
        with tempfile.TemporaryDirectory() as directory:
            keys = Path(directory) / 'nes-keys.txt'
            keys.write_text('ON START RIGHT')
            out.poll_nes_apu(guest, 300_000, keys)
        self.assertEqual(guest.data[36:38], bytes((0x88, 1)))
        out.close()


if __name__ == '__main__':
    unittest.main()


class PathTests(unittest.TestCase):
    def test_ascii_and_utf16_paths_are_decoded(self):
        from audio_hle import decode_path
        self.assertEqual(decode_path(b'/LGAPP/a.aac\0junk'), '/LGAPP/a.aac')
        self.assertEqual(decode_path('/LGAPP/b.mid'.encode('utf-16-le') + b'\0\0xx'), '/LGAPP/b.mid')

    def test_media_path_is_resolved_by_full_path_or_by_name(self):
        import tempfile
        from pathlib import Path
        from audio_hle import resolve_media
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'LGAPP/Media/Sounds').mkdir(parents=True)
            target = root / 'LGAPP/Media/Sounds/Power On.aac'
            target.write_bytes(b'x')
            self.assertEqual(resolve_media('/LGAPP/Media/Sounds/Power On.aac', root), target)
            self.assertEqual(resolve_media('/other/dir/power on.AAC', root), target)
            self.assertIsNone(resolve_media('/nope.mp3', root))

    def test_unknown_formats_are_skipped_not_crashed(self):
        from pathlib import Path
        from audio_hle import FilePlayer
        player = FilePlayer()
        self.assertFalse(player.play(Path('/tmp/x.xyz')))
        self.assertEqual(player.skipped, ['x.xyz'])

    def test_missing_mmf_file_is_skipped_not_crashed(self):
        from pathlib import Path
        from audio_hle import FilePlayer
        player = FilePlayer()
        self.assertFalse(player.play(Path('/tmp/does-not-exist.mmf')))
        self.assertEqual(player.skipped, ['does-not-exist.mmf'])


class DspCommandTests(unittest.TestCase):
    def test_oscillator_coefficients_give_the_keypad_frequencies(self):
        from audio_hle import coefficient_frequency
        self.assertAlmostEqual(coefficient_frequency(0x34a4), 770, delta=3)
        self.assertAlmostEqual(coefficient_frequency(0x1fe2), 1336, delta=5)

    def test_tone_command_starts_and_stops(self):
        out = AudioOutput()
        out.dsp_command(0x302, [0x1fe2, 0x34a4, 0x15, 0x500, 0x51, 4])
        self.assertEqual(out.tones_started, 1)
        self.assertEqual(len(out.frequencies), 2)
        out.dsp_command(0x302, [0, 0, 0, 0x500, 0, 4])
        self.assertIsNone(out.frequencies)
        out.dsp_command(0x301, [1, 2, 3])
        self.assertEqual(out.tones_started, 1)
        out.close()


class MidiStreamTests(unittest.TestCase):
    """QDSP QSYNTH mailbox: a plain running-status MIDI byte stream, fed to MidiStream in arbitrary chunks."""

    def stream(self):
        from audio_hle import MidiStream
        stream = MidiStream()
        self.calls = []
        stream.send = self.calls.append   # record outgoing fluidsynth shell commands instead of spawning one
        return stream

    def test_note_on_and_off_are_dispatched(self):
        stream = self.stream()
        stream.feed(bytes([0x90, 0x3c, 0x64, 0x80, 0x3c, 0x00]))
        self.assertEqual(self.calls, ['noteon 0 60 100', 'noteoff 0 60'])
        self.assertEqual(stream.notes, 1)

    def test_running_status_reuses_the_last_status_byte(self):
        stream = self.stream()
        stream.feed(bytes([0x90, 0x3c, 0x64, 0x3e, 0x50, 0x3c, 0x00]))   # noteon, another noteon, then a note-on with velocity 0 (= note-off)
        self.assertEqual(self.calls, ['noteon 0 60 100', 'noteon 0 62 80', 'noteoff 0 60'])

    def test_a_message_split_across_chunks_is_carried_over(self):
        stream = self.stream()
        stream.feed(bytes([0x90, 0x3c]))
        stream.feed(bytes([0x64]))
        self.assertEqual(self.calls, ['noteon 0 60 100'])

    def test_sysex_is_skipped_even_across_chunks(self):
        stream = self.stream()
        stream.feed(bytes([0xf0, 0x7f, 0x7f]))
        stream.feed(bytes([0x04, 0x7f, 0xf7, 0xc0, 0x05]))
        self.assertEqual(self.calls, ['prog 0 5'])

    def test_control_change_program_and_pitch_bend(self):
        stream = self.stream()
        stream.feed(bytes([0xb0, 0x07, 0x7f, 0xc0, 0x28, 0xe0, 0x00, 0x40]))
        self.assertEqual(self.calls, ['cc 0 7 127', 'prog 0 40', 'pitch_bend 0 8192'])

    def test_reset_sends_all_notes_off_on_every_channel_and_clears_state(self):
        stream = self.stream()
        stream.feed(bytes([0x90, 0x3c]))   # a note-on status byte with its data byte pending
        stream.reset()
        self.assertEqual(len(self.calls), 16)
        self.assertTrue(all(c.startswith('cc ') and c.endswith(' 123 0') for c in self.calls))
        self.assertEqual(stream.pending, b'')
        self.assertEqual(stream.status, 0)
