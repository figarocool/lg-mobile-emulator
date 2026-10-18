"""Frame sources for the emulated camera sensors: test pattern, image/video file, host webcam (ffmpeg, v4l2).

Every source returns one RGB frame (height, width, 3 uint8) for a given size, or None when no frame is available yet.
"""
import shutil
import subprocess
import threading
from pathlib import Path

import numpy as np


def rgb_to_nv12(rgb):
    """rgb: (h, w, 3) uint8 with even h and w -> NV12 bytes (BT.601 full range)."""
    r, g, b = (rgb[:, :, i].astype(np.float32) for i in range(3))
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    h, w = y.shape
    cb = cb.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))
    cr = cr.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))
    chroma = np.empty((h // 2, w), np.uint8)
    chroma[:, 0::2] = np.clip(cb, 0, 255)
    chroma[:, 1::2] = np.clip(cr, 0, 255)
    return np.clip(y, 0, 255).astype(np.uint8).tobytes() + chroma.tobytes()


def rgb_to_565(rgb):
    r, g, b = (rgb[:, :, i].astype(np.uint16) for i in range(3))
    return (((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)).astype('<u2').tobytes()


def rgb_to_yuyv(rgb):
    """YCbCr 4:2:2 interleaved (Y0 Cb Y1 Cr)."""
    r, g, b = (rgb[:, :, i].astype(np.float32) for i in range(3))
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    out = np.empty(rgb.shape[:2][0:1] + (rgb.shape[1] * 2,), np.uint8)
    out[:, 0::4] = np.clip(y[:, 0::2], 0, 255)
    out[:, 1::4] = np.clip((cb[:, 0::2] + cb[:, 1::2]) / 2, 0, 255)
    out[:, 2::4] = np.clip(y[:, 1::2], 0, 255)
    out[:, 3::4] = np.clip((cr[:, 0::2] + cr[:, 1::2]) / 2, 0, 255)
    return out.tobytes()


def rgb_to_packed422(rgb, order):
    """Packed 4:2:2 in the byte order given by a permutation of 'YUYV' style letters, e.g. 'UYVY'."""
    yuyv = np.frombuffer(rgb_to_yuyv(rgb), np.uint8).reshape(rgb.shape[0], -1, 4)
    slots = {'Y0': yuyv[:, :, 0], 'U': yuyv[:, :, 1], 'Y1': yuyv[:, :, 2], 'V': yuyv[:, :, 3]}
    names = {'YUYV': ('Y0', 'U', 'Y1', 'V'), 'UYVY': ('U', 'Y0', 'V', 'Y1'), 'YVYU': ('Y0', 'V', 'Y1', 'U'), 'VYUY': ('V', 'Y0', 'U', 'Y1')}[order]
    out = np.stack([slots[n] for n in names], axis=-1)
    return out.astype(np.uint8).tobytes()


ENCODERS = {'uyvy': lambda rgb: rgb_to_packed422(rgb, 'UYVY'), 'yvyu': lambda rgb: rgb_to_packed422(rgb, 'YVYU'),
            'vyuy': lambda rgb: rgb_to_packed422(rgb, 'VYUY'),'rgb565': rgb_to_565, 'yuyv': rgb_to_yuyv, 'nv12': rgb_to_nv12}


def fit(rgb, width, height):
    from PIL import Image
    return np.asarray(Image.fromarray(rgb).resize((width, height), Image.BILINEAR))


class TestPattern:
    name = 'test'

    def __init__(self):
        self.n = 0

    def frame(self, width, height):
        bars = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0)]
        rgb = np.zeros((height, width, 3), np.uint8)
        for i, color in enumerate(bars):
            rgb[:, i * width // 8:(i + 1) * width // 8] = color
        x = (self.n * 6) % max(1, width - 40)
        rgb[height // 2 - 20:height // 2 + 20, x:x + 40] = (255, 128, 0)
        self.n += 1
        return rgb


class ImageFile:
    name = 'image'

    def __init__(self, path):
        from PIL import Image
        self.image = np.asarray(Image.open(path).convert('RGB'))

    def frame(self, width, height):
        return fit(self.image, width, height)


class Webcam:
    """Latest frame of a host video device, grabbed by an ffmpeg process at the size asked for."""
    name = 'webcam'

    def __init__(self, device='/dev/video0'):
        self.device = device
        self.size = None
        self.latest = None
        self.process = None
        self.lock = threading.Lock()

    def start(self, width, height):
        self.stop()
        self.size = (width, height)
        if not shutil.which('ffmpeg') or not Path(self.device).exists():
            return
        self.process = subprocess.Popen(
            ['ffmpeg', '-loglevel', 'quiet', '-f', 'v4l2', '-framerate', '15', '-i', self.device, '-vf', f'scale={width}:{height}',
             '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self.pump, args=(self.process, width, height), daemon=True).start()

    def pump(self, process, width, height):
        size = width * height * 3
        while process.poll() is None:
            data = process.stdout.read(size)
            if len(data) < size:
                break
            with self.lock:
                self.latest = np.frombuffer(data, np.uint8).reshape(height, width, 3)

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
        self.process = None
        self.latest = None

    def frame(self, width, height):
        if self.size != (width, height) or self.process is None:
            self.start(width, height)
        with self.lock:
            rgb = self.latest
        return rgb


class Solid:
    name = 'solid'

    def __init__(self, color):
        self.color = color

    def frame(self, width, height):
        return np.full((height, width, 3), self.color, np.uint8)


def make_source(spec):
    """'test', 'webcam[:device]' or a path to an image."""
    spec = spec or 'test'
    if spec == 'test':
        return TestPattern()
    if spec.startswith('solid:'):
        return Solid(tuple(int(x) for x in spec[6:].split(',')))
    if spec.startswith('webcam'):
        return Webcam(spec.partition(':')[2] or '/dev/video0')
    return ImageFile(spec)
