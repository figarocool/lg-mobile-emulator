"""SMAF (.mmf, Yamaha MA-2/MA-3 phone melodies) to Standard MIDI File converter.

The phone's FM synthesizer is not reproduced: the note sequence is converted to MIDI and rendered with a General MIDI
sound font. Only the score tracks (chunk 'MTR') are used; PCM audio tracks ('ATR') are reported and skipped.

Layout (recovered from the files in the firmware's media area): 'MMMD' size, then chunks id(4)+size(4): 'CNTI' (content
info), 'OPDA' (optional data), 'MTR<version>' (score track: format, sequence type, duration time base, gate time base,
16 channel status bytes, then sub-chunks 'Mtsu' setup SysEx and 'Mtsq' sequence), 'ATR' (audio track).
Sequence events: duration (1 byte, or 2 bytes with bit 7 set: ((b0&0x7f)<<7|b1)+128), then a status byte:
0x8n note+gate, 0x9n note+velocity+gate, 0xBn controller, 0xCn program, 0xEn pitch bend, 0xF0 SysEx, 0xFF 0x2F 0x00 end.
"""
import struct

TIMEBASE_MS = {0x00: 1, 0x01: 2, 0x02: 4, 0x03: 5, 0x10: 10, 0x11: 20, 0x12: 40, 0x13: 50}


class SmafError(ValueError):
    pass


def varlen_smaf(data, i):
    b = data[i]
    if b & 0x80:
        return (((b & 0x7f) << 7) | data[i + 1]) + 128, i + 2
    return b, i + 1


def midi_varlen(value):
    out = [value & 0x7f]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7f))
        value >>= 7
    return bytes(reversed(out))


def chunks(data, start, end):
    i = start
    while i + 8 <= end:
        cid = data[i:i + 4]
        size = struct.unpack_from('>I', data, i + 4)[0]
        yield cid, data[i + 8:i + 8 + size]
        i += 8 + size


def parse_score(body):
    """Return (events, notes) where events are (time_ms, kind, bytes) for one MTR chunk body."""
    fmt, seq_type, tb_d, tb_g = body[0], body[1], body[2], body[3]
    d_ms = TIMEBASE_MS.get(tb_d, 4)
    g_ms = TIMEBASE_MS.get(tb_g, 4)
    sequence = None
    for cid, content in chunks(body, 20, len(body)):
        if cid == b'Mtsq':
            sequence = content
    if sequence is None:
        raise SmafError('score track without Mtsq')
    events = []
    t = 0
    i = 0
    n = len(sequence)
    while i < n:
        delta, i = varlen_smaf(sequence, i)
        t += delta * d_ms
        status = sequence[i]
        i += 1
        kind = status & 0xf0
        ch = status & 0x0f
        if status == 0xff:
            if sequence[i] == 0x2f:
                break
            i += 2
        elif status == 0xf0:
            length, i = varlen_smaf(sequence, i)
            i += length
        elif kind == 0x80:
            note = sequence[i]; gate, i = varlen_smaf(sequence, i + 1)
            events.append((t, ch, 'note', note, 64, gate * g_ms))
        elif kind == 0x90:
            note, vel = sequence[i], sequence[i + 1]; gate, i = varlen_smaf(sequence, i + 2)
            events.append((t, ch, 'note', note, vel, gate * g_ms))
        elif kind == 0xb0:
            events.append((t, ch, 'cc', sequence[i], sequence[i + 1], 0)); i += 2
        elif kind == 0xc0:
            events.append((t, ch, 'pc', sequence[i], 0, 0)); i += 1
        elif kind == 0xe0:
            events.append((t, ch, 'bend', sequence[i], sequence[i + 1], 0)); i += 2
        else:
            raise SmafError(f'unknown sequence status {status:#x}')
    return events


def to_midi(data):
    """SMAF file bytes -> Standard MIDI File bytes (type 0, 1 tick = 1 ms)."""
    if data[:4] != b'MMMD':
        raise SmafError('not a SMAF file')
    size = struct.unpack_from('>I', data, 4)[0]
    events = []
    for cid, body in chunks(data, 8, min(len(data), 8 + size)):
        if cid[:3] == b'MTR':
            events += parse_score(body)
    if not events:
        raise SmafError('no score track')
    raw = []
    for t, ch, kind, a, b, gate in events:
        if kind == 'note':
            raw.append((t, 1, bytes([0x90 | ch, a, b or 64])))
            raw.append((t + max(gate, 1), 0, bytes([0x80 | ch, a, 0])))
        elif kind == 'cc':
            raw.append((t, 0, bytes([0xb0 | ch, a, b])))
        elif kind == 'pc':
            raw.append((t, 0, bytes([0xc0 | ch, a])))
        else:
            raw.append((t, 0, bytes([0xe0 | ch, a, b])))
    raw.sort(key=lambda e: (e[0], e[1]))
    track = bytearray(b'\x00\xff\x51\x03\x0f\x42\x40')          # 1,000,000 us per quarter note
    last = 0
    for t, _, message in raw:
        track += midi_varlen(t - last) + message
        last = t
    track += b'\x00\xff\x2f\x00'
    return b'MThd' + struct.pack('>IHHH', 6, 0, 1, 1000) + b'MTrk' + struct.pack('>I', len(track)) + bytes(track)


def duration_ms(data):
    midi_events = 0
    end = 0
    size = struct.unpack_from('>I', data, 4)[0]
    for cid, body in chunks(data, 8, min(len(data), 8 + size)):
        if cid[:3] == b'MTR':
            for t, ch, kind, a, b, gate in parse_score(body):
                end = max(end, t + (gate if kind == 'note' else 0))
    return end


if __name__ == '__main__':
    import sys
    from pathlib import Path
    for name in sys.argv[1:]:
        raw = Path(name).read_bytes()
        print(name, duration_ms(raw), 'ms')
