import unittest
import numpy as np
from audio_hle import tone_frequencies, render, RATE, AudioOutput


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


class OutputTests(unittest.TestCase):
    def test_output_without_audio_tools_does_not_crash(self):
        out = AudioOutput()
        out.start_tone((697, 1209), 0.5)
        out.stop_tone()
        self.assertEqual(out.tones_started, 1)
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
        self.assertFalse(player.play(Path('/tmp/x.mmf')))
        self.assertEqual(player.skipped, ['x.mmf'])


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
