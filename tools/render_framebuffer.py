"""Render captured loader RAM as candidate RGB565 pixels, without drawing UI."""
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
for name, width, height in [('main', 176, 220), ('sub', 96, 96)]:
    source = ROOT / 'analysis' / f'code_{name}_framebuffer.raw'
    if not source.exists():
        continue
    data = source.read_bytes()
    if len(data) != width*height*2:
        raise ValueError('Unexpected framebuffer length')
    rgb = bytearray()
    for (pixel,) in struct.iter_unpack('<H', data):
        rgb.extend((((pixel >> 11) & 31)*255//31,
                    ((pixel >> 5) & 63)*255//63, (pixel & 31)*255//31))
    output = source.with_suffix('.ppm')
    output.write_bytes(f'P6\n{width} {height}\n255\n'.encode()+rgb)
    print(output)
