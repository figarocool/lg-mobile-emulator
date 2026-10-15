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
        self.requests = []
        self.raw_requests = []
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
                if frequencies:
                    self.position += self.CHUNK
            if not frequencies:
                time.sleep(0.01)
                continue
            try:
                self.process.stdin.write(render(frequencies, position, self.CHUNK, volume))
                self.process.stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                return

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
