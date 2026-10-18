"""Audio component of the emulator: the phone's sound service, rendered on the host.

The MSM6250 plays sound through the QDSP, whose microcode the emulator does not execute. So, like a
high-level emulation, this component sits at the firmware's sound service: it watches the calls the
SND task makes ("Starting a tone" / "Stopping a tone"), synthesizes the sound itself and sends it to
the host audio device. It is a model, not the DSP: tone identifiers and amplitudes are inferred.

Key tones: the firmware passes 1000 + n, with n = 1..10 for digits 0..9, 11 for '*' and 12 for '#'
(observed for 0,1,5,9); they are rendered as the standard DTMF pairs.
"""
import math
import os
import struct
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3

RATE = 16000
MEDIA_ROOT = Path(__file__).resolve().parents[1] / 'extracted' / 'MEDIA'
SOUND_FONTS = ('/usr/share/sounds/sf2/FluidR3_GM.sf2', '/usr/share/sounds/sf2/default-GM.sf2',
               '/usr/share/sounds/sf2/TimGM6mb.sf2')
SENDERS = (0x7c0654, 0xb8f47c, 0xeee1fc, 0x12dd490, 0x12dd484, 0xeee210, 0x7c07dc)
LOW = (941, 697, 697, 697, 770, 770, 770, 852, 852, 852, 941, 941)       # rows: 0,1..9,*,#
HIGH = (1336, 1209, 1336, 1477, 1209, 1336, 1477, 1209, 1336, 1477, 1209, 1477)
MAX_VOLUME = 0x6f


def tone_frequencies(tone_id):
    """Frequencies for a firmware tone id, or None when the id is not a key tone."""
    index = tone_id - 1001
    if 0 <= index < 12:
        return (LOW[index], HIGH[index])
    return None


def render(frequencies, start, count, volume=1.0):
    """Samples [start, start+count) of a sum of sines, 16-bit signed little endian bytes."""
    out = bytearray()
    amplitude = 9000 * max(0.0, min(1.0, volume)) / max(1, len(frequencies))
    for n in range(start, start + count):
        value = sum(math.sin(2 * math.pi * f * n / RATE) for f in frequencies) * amplitude
        out += int(value).to_bytes(2, 'little', signed=True)
    return bytes(out)


def render_nes_apu(registers, start, count):
    """Small host-side square/triangle/noise renderer for the NES APU register snapshot."""
    out = bytearray()
    enabled = registers[0x15] if len(registers) > 0x15 else 0
    pulses = []
    for channel, base in enumerate((0, 4)):
        if not enabled & (1 << channel):
            continue
        timer = registers[base + 2] | ((registers[base + 3] & 7) << 8)
        if timer < 8:
            continue
        duty = (0.125, 0.25, 0.5, 0.75)[registers[base] >> 6]
        volume = (registers[base] & 15) or 8
        pulses.append((1789773.0 / (16 * (timer + 1)), duty, volume / 15.0))
    triangle = None
    if enabled & 4:
        timer = registers[10] | ((registers[11] & 7) << 8)
        if timer >= 2:
            triangle = 1789773.0 / (32 * (timer + 1))
    noise = bool(enabled & 8 and registers[12] & 15)
    for n in range(start, start + count):
        sample = 0.0
        for frequency, duty, volume in pulses:
            sample += (1.0 if (n * frequency / RATE) % 1.0 < duty else -1.0) * volume * 1900
        if triangle:
            phase = (n * triangle / RATE) % 1.0
            sample += (1.0 - 4.0 * abs(phase - 0.5)) * 850
        if noise and ((n * 1103515245 + 12345) >> 16) & 1:
            sample += 650
        out += max(-32768, min(32767, int(sample))).to_bytes(2, 'little', signed=True)
    return bytes(out)


def decode_path(raw):
    """C string from guest memory: ASCII or UTF-16LE (second byte zero)."""
    if len(raw) > 1 and raw[1] == 0:
        text = raw.decode('utf-16-le', 'ignore').split('\0')[0]
    else:
        text = raw.split(b'\0')[0].decode('latin1')
    return text


PATH_WINDOW = (0x1bf4000, 0x2000)  # RAM page where the media player keeps the selected file path


def current_media_path(uc):
    """Path of the file the media player is about to play, read from the firmware's own buffers."""
    try:
        data = bytes(uc.mem_read(*PATH_WINDOW))
    except Exception:
        return ''
    start = data.find(b'/LGAPP/')
    while start >= 0:
        text = decode_path(data[start:start + 160])
        if resolve_media(text):
            return text
        start = data.find(b'/LGAPP/', start + 1)
    return ''


def find_in_memory(uc):
    hits = []
    for begin in range(0x1b00000, 0x1c80000, 0x10000):
        try:
            data = bytes(uc.mem_read(begin, 0x10000))
        except Exception:
            continue
        i = data.find(b'Clock Bell')
        while i >= 0 and len(hits) < 6:
            hits.append(hex(begin + i))
            i = data.find(b'Clock Bell', i + 1)
    return hits


def resolve_media(path, root=MEDIA_ROOT):
    """Find the original media file a firmware path refers to (the flash was installed from it)."""
    name = path.replace('\\', '/').lstrip('/')
    direct = root / name
    if direct.is_file():
        return direct
    base = name.rsplit('/', 1)[-1].lower()
    for candidate in root.rglob('*'):
        if candidate.is_file() and candidate.name.lower() == base:
            return candidate
    return None


class FilePlayer:
    """Plays one media file at a time on the host: MIDI through fluidsynth, the rest through ffplay."""

    def __init__(self):
        self.process = None
        self.current = None
        self.started = 0
        self.skipped = []

    def command(self, file):
        suffix = file.suffix.lower()
        if suffix == '.mmf':
            # SMAF phone melody: convert the score to MIDI (tools/smaf.py) and render it like any MIDI file
            import smaf
            try:
                midi = Path(tempfile.gettempdir()) / f'u310-{file.stem.replace(" ", "_")}-smaf.mid'
                midi.write_bytes(smaf.to_midi(file.read_bytes()))
            except (smaf.SmafError, IndexError, struct.error, OSError):
                return None
            file, suffix = midi, '.mid'
        if suffix in ('.mid', '.midi') and shutil.which('fluidsynth') and shutil.which('ffplay'):
            font = next((f for f in SOUND_FONTS if os.path.exists(f)), None)
            if font:
                wav = Path(tempfile.gettempdir()) / f'u310-{file.stem.replace(" ", "_")}.wav'
                if not wav.exists():
                    subprocess.run(['fluidsynth', '-ni', '-q', '-F', str(wav), '-r', '44100', font, str(file)],
                                   capture_output=True, timeout=60)
                return ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', str(wav)] if wav.exists() else None
        if suffix in ('.mp3', '.aac', '.wav', '.amr', '.3gp', '.m4a', '.mp4', '.qcp', '.awb') and shutil.which('ffplay'):
            return ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', str(file)]
        return None

    def play(self, file):
        self.stop()
        command = self.command(file)
        if not command:
            self.skipped.append(file.name)  # e.g. SMAF (.mmf), which has no host decoder here
            return False
        self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.current = file.name
        self.started += 1
        return True

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
        self.process = None
        self.current = None


class MidiStream:
    """Renders the QDSP QSYNTH image's raw MIDI byte stream (qdsp_model.QdspModel.synth_status) live, through a
    persistent FluidSynth process driven by its interactive shell commands (noteon/noteoff/cc/prog/pitch_bend).

    The stream uses MIDI running status and can carry SysEx (skipped); only plain channel-voice messages are
    rendered. This is the live counterpart of FilePlayer's offline MIDI/SMAF rendering: here the firmware itself
    is playing the notes (ringtone preview, alerts), one small chunk at a time, so the only option is to keep a
    synth running and feed it as data arrives.
    """

    LENGTHS = {0x8: 2, 0x9: 2, 0xa: 2, 0xb: 2, 0xc: 1, 0xd: 1, 0xe: 2}  # data bytes following the status byte

    def __init__(self):
        self.process = None
        self.status = 0
        self.pending = b''
        self.font = next((f for f in SOUND_FONTS if os.path.exists(f)), None)
        self.notes = 0

    def ensure(self):
        if self.process is not None or not self.font or not shutil.which('fluidsynth'):
            return
        driver = 'pulseaudio' if shutil.which('pacat') else 'alsa'
        try:
            self.process = subprocess.Popen(['fluidsynth', '-a', driver, '-l', '-q', '-g', '1', self.font],
                                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        except OSError:
            self.process = None

    def send(self, line):
        self.ensure()
        if not self.process:
            return
        try:
            self.process.stdin.write(line + '\n')
            self.process.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            self.process = None

    def feed(self, chunk):
        """Parse and play one mailbox chunk; a message split across chunks is carried over in self.pending."""
        data = self.pending + chunk
        self.pending = b''
        i, n = 0, len(data)
        while i < n:
            byte = data[i]
            if byte == 0xf0:
                end = data.find(b'\xf7', i)
                if end < 0:
                    self.pending = data[i:]
                    return
                i = end + 1
                continue
            if byte & 0x80:
                if byte >= 0xf8:          # system realtime: no data, running status unaffected
                    i += 1
                    continue
                if 0xf1 <= byte < 0xf7:   # system common: not expected here, drop the status byte
                    self.status = 0
                    i += 1
                    continue
                self.status = byte
                i += 1
            need = self.LENGTHS.get(self.status >> 4)
            if need is None:
                i += 1
                continue
            if i + need > n:
                self.pending = data[max(0, i - 1):]
                return
            self.dispatch(self.status, data[i:i + need])
            i += need

    def dispatch(self, status, args):
        kind, channel = status & 0xf0, status & 0x0f
        if kind == 0x90 and args[1]:
            self.send(f'noteon {channel} {args[0]} {args[1]}')
            self.notes += 1
        elif kind in (0x80, 0x90):
            self.send(f'noteoff {channel} {args[0]}')
        elif kind == 0xb0:
            self.send(f'cc {channel} {args[0]} {args[1]}')
        elif kind == 0xc0:
            self.send(f'prog {channel} {args[0]}')
        elif kind == 0xe0:
            self.send(f'pitch_bend {channel} {args[0] | (args[1] << 7)}')

    def reset(self):
        for channel in range(16):
            self.send(f'cc {channel} 123 0')   # all notes off
        self.pending = b''
        self.status = 0

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
            except OSError:
                pass
            self.process = None


class AudioOutput:
    """Plays the active tone through pacat/aplay; silent when no audio tool is available."""

    CHUNK = 320  # 20 ms

    def __init__(self):
        command = None
        if shutil.which('pacat'):
            command = ['pacat', '--playback', '--raw', f'--rate={RATE}', '--channels=1', '--format=s16le',
                       '--latency-msec=50']
        elif shutil.which('aplay'):
            command = ['aplay', '-q', '-t', 'raw', '-r', str(RATE), '-f', 'S16_LE', '-c', '1', '-B', '50000']
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL) if command else None
        self.frequencies = None
        self.volume = 1.0
        self.position = 0
        self.tones_started = 0
        self.from_dsp = False
        self.files = FilePlayer()
        self.midi = MidiStream()
        self.requests = []
        self.raw_requests = []
        self.nes_apu = None
        self.nes_apu_sequence = None
        self.nes_apu_bridge = None
        self.nes_scan_cursor = 0x01000000
        self.nes_scan_at = 0
        self.nes_notes = 0
        self.nes_input_poll_at = 0
        self.nes_input_mtime = None
        self.nes_keypad_mtime = None
        self.nes_host_pad = 0
        self.nes_host_enabled = True
        self.nes_last_sequence_at = 0.0
        self.nes_active_file = None
        self.lock = threading.Lock()
        self.closed = False
        if self.process:
            threading.Thread(target=self.pump, daemon=True).start()

    def start_tone(self, frequencies, volume):
        with self.lock:
            self.frequencies, self.volume, self.position = frequencies, volume, 0
            self.tones_started += 1

    def stop_tone(self):
        with self.lock:
            self.frequencies = None

    def pump(self):
        while not self.closed:
            with self.lock:
                frequencies, volume, position = self.frequencies, self.volume, self.position
                apu = self.nes_apu
                if frequencies or apu:
                    self.position += self.CHUNK
            if apu:
                try:
                    self.process.stdin.write(render_nes_apu(apu, position, self.CHUNK))
                    self.process.stdin.flush()
                except (BrokenPipeError, ValueError, OSError):
                    return
                continue
            if not frequencies:
                time.sleep(0.01)
                continue
            try:
                self.process.stdin.write(render(frequencies, position, self.CHUNK, volume))
                self.process.stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                return

    def poll_nes_apu(self, uc, instructions, keys_file=None, keypad_file=None):
        """Find and sample the NES PXO's private register snapshot once it is loaded."""
        if (keys_file or keypad_file) and instructions - self.nes_input_poll_at >= 250_000:
            self.nes_input_poll_at = instructions
            try:
                path = Path(keys_file) if keys_file else None
                key_mtime = path.stat().st_mtime_ns if path and path.exists() else None
                keypad_path = Path(keypad_file) if keypad_file else None
                keypad_mtime = keypad_path.stat().st_mtime_ns if keypad_path and keypad_path.exists() else None
                if key_mtime != self.nes_input_mtime or keypad_mtime != self.nes_keypad_mtime:
                    self.nes_input_mtime, self.nes_keypad_mtime = key_mtime, keypad_mtime
                    words = path.read_text().split() if path and path.exists() else ['OFF']
                    masks = {'A':1,'B':2,'SELECT':4,'START':8,'UP':16,'DOWN':32,'LEFT':64,'RIGHT':128}
                    if words and words[0] == 'ON':
                        self.nes_host_pad = sum(masks.get(word, 0) for word in words[1:])
                    elif keypad_path and keypad_path.exists():
                        pressed = set(keypad_path.read_text().split())
                        matrix = {'1,1':'UP','3,1':'DOWN','2,2':'LEFT','2,0':'RIGHT',
                                  '1,2':'A','3,2':'B','2,3':'START','4,2':'SELECT'}
                        self.nes_host_pad = sum(masks[action] for pos, action in matrix.items() if pos in pressed)
                    else:
                        self.nes_host_pad = 0
            except OSError:
                self.nes_host_pad = 0
        if self.nes_apu_bridge is None and instructions - self.nes_scan_at >= 4_000_000:
            self.nes_scan_at = instructions
            end = min(self.nes_scan_cursor + 0x200000, 0x05000000)
            if end > self.nes_scan_cursor:
                try:
                    raw = bytes(uc.mem_read(self.nes_scan_cursor, end - self.nes_scan_cursor))
                    i = raw.find(b'NES1APU1')
                    if i >= 0:
                        self.nes_apu_bridge = self.nes_scan_cursor + i
                except Exception:
                    pass
                self.nes_scan_cursor = end
        if self.nes_apu_bridge is None:
            return
        try:
            base = self.nes_apu_bridge
            uc.mem_write(base + 36, bytes((self.nes_host_pad, int(self.nes_host_enabled))))
            sequence = int.from_bytes(uc.mem_read(base + 8, 4), 'little')
            if sequence == self.nes_apu_sequence:
                if self.nes_active_file and time.monotonic() - self.nes_last_sequence_at > 2.0:
                    Path(self.nes_active_file).unlink(missing_ok=True)
                return
            registers = bytes(uc.mem_read(base + 12, 24))
        except Exception:
            return
        self.nes_apu_sequence = sequence
        self.nes_last_sequence_at = time.monotonic()
        if keys_file:
            self.nes_active_file = str(Path(keys_file).with_name('nes-active'))
            Path(self.nes_active_file).write_text('1')
        with self.lock:
            self.nes_apu = registers if registers[0x15] & 0x0f else None
            if self.nes_apu:
                self.nes_notes += 1

    def dsp_command(self, command, payload):
        """Command 0x302 starts (nonzero coefficients) or stops the two-oscillator tone generator."""
        if command != 0x302:
            return
        frequencies = tuple(round(coefficient_frequency(c)) for c in payload[:2] if c)
        if frequencies:
            self.start_tone(frequencies, 0.8)
        else:
            self.stop_tone()

    def play_file(self, path):
        self.requests.append(path)
        file = resolve_media(path)
        if file:
            return self.files.play(file)
        return False

    def close(self):
        self.closed = True
        self.files.stop()
        self.midi.stop()
        if self.process and self.process.poll() is None:
            self.process.terminate()


def coefficient_frequency(coefficient):
    """Frequency of an oscillator coefficient c = 2*cos(w) in Q13 at 8 kHz (DSP tone command 0x302)."""
    cosine = max(-1.0, min(1.0, coefficient / 16384))
    return math.acos(cosine) * 8000 / (2 * math.pi)


def attach(uc, state, dsp=None, output=None):
    output = output or AudioOutput()
    if dsp is not None and dsp.qdsp is not None:
        dsp.qdsp.listeners.append(output.dsp_command)
        dsp.qdsp.synth_listeners.append(output.midi.feed)
        dsp.qdsp.synth_reset_listeners.append(output.midi.reset)
        output.from_dsp = True

    def observe(u, address, size, _):
        try:
            fmt_pointer = int.from_bytes(u.mem_read(u.reg_read(UC_ARM_REG_R0) + 8, 4), 'little')
            text = bytes(u.mem_read(fmt_pointer, 40)).split(b'\0')[0]
        except Exception:
            return
        if text.startswith(b'TONE:') and not output.from_dsp:
            # the firmware has already resolved the tone id to two frequencies in Hz
            low, high = u.reg_read(UC_ARM_REG_R1), u.reg_read(UC_ARM_REG_R2)
            frequencies = tuple(f for f in dict.fromkeys((low, high)) if 0 < f < RATE // 2)
            if frequencies:
                output.start_tone(frequencies, 0.8)
        elif text.startswith(b'Stopping a tone') and not output.from_dsp:
            output.stop_tone()
        elif text.startswith(b'[LGOEM_Play_AudioPlayer]'):
            output.play_file(current_media_path(u))
            if os.environ.get('U310_AUDIO_DEBUG'):
                output.raw_requests.append(find_in_memory(u))
        elif text.startswith((b'SNDAPI_StopAudioPlayer', b'[LGOEM_Play_Cmx]LGOEM_Stop_Cmx')):
            output.files.stop()

    for address in SENDERS:
        uc.hook_add(UC_HOOK_CODE, observe, begin=address, end=address)
    return output
