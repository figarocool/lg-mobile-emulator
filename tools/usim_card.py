"""Minimal USIM/UICC model for the T=0 protocol, independent of any UART.

Feed it the bytes the phone transmits; it returns the bytes the card answers with.
It is a model written from ISO 7816-3/-4 and ETSI TS 102 221 / 31.102, not a dump of a real SIM:
file contents are plausible defaults for an Italian H3G subscriber (MCC 222, MNC 99).
"""

# Commands whose APDU carries data from the terminal to the card (case 3/4).
from sim_profile import msisdn_record  # noqa: E402

DATA_IN = {0xa2, 0xa4, 0x20, 0x24, 0x26, 0x28, 0x2c, 0x10, 0x14, 0xc2, 0xd6, 0xdc, 0x88, 0xe2, 0xda}
USIM_AID = bytes.fromhex('a0000000871002ff49ff0589')


def bcd_swap(digits):
    """Nibble-swapped BCD, padded with F."""
    digits = digits + ('f' if len(digits) % 2 else '')
    return bytes(int(digits[i + 1] + digits[i], 16) for i in range(0, len(digits), 2))


def imsi_bytes(imsi):
    """EF_IMSI: length byte, then digits with the parity nibble first (odd count => 9)."""
    odd = len(imsi) % 2
    digits = ('9' if odd else '1') + imsi
    return bytes([len(digits) // 2]) + bcd_swap(digits)


class EF:
    def __init__(self, fid, data=b'', record_length=None, records=None, sfi=None, cyclic=False, arr=1):
        self.fid = fid
        self.kind = 'EF'
        self.sfi = sfi
        self.arr = arr
        self.compact_security = False
        if records is not None:
            self.structure = 'cyclic' if cyclic else 'linear'
            self.records = [bytearray(r) for r in records]
            self.record_length = record_length or len(records[0])
        else:
            self.structure = 'transparent'
            self.data = bytearray(data)

    @property
    def size(self):
        if self.structure == 'transparent':
            return len(self.data)
        return self.record_length * len(self.records)

    def fcp(self):
        if self.structure == 'transparent':
            descriptor = bytes([0x82, 0x02, 0x01, 0x21])
        else:
            descriptor = bytes([0x82, 0x05, 0x06 if self.structure == 'cyclic' else 0x02, 0x21,
                                self.record_length >> 8, self.record_length & 0xff, len(self.records)])
        body = (descriptor + bytes([0x83, 0x02, self.fid >> 8, self.fid & 0xff])
                + bytes([0xa5, 0x03, 0x80, 0x01, 0x71])
                + bytes([0x8a, 0x01, 0x05])
                + (bytes.fromhex('8c03030000') if self.compact_security else bytes([0x8b, 0x03, 0x2f, 0x06, self.arr]))
                + bytes([0x80, 0x02, self.size >> 8, self.size & 0xff]))
        if self.sfi:
            body += bytes([0x88, 0x01, self.sfi << 3])
        return bytes([0x62, len(body)]) + body


class DF:
    pin_enabled = True  # PS_DO bit in the FCP of every DF; set by the card model

    def __init__(self, fid, kind='DF', aid=None, children=()):
        self.fid = fid
        self.kind = kind
        self.aid = aid
        self.children = {c.fid: c for c in children}

    def fcp(self):
        body = bytes([0x82, 0x02, 0x78, 0x21, 0x83, 0x02, self.fid >> 8, self.fid & 0xff])
        if self.aid:
            body += bytes([0x84, len(self.aid)]) + self.aid
        body += bytes([0xa5, 0x03, 0x80, 0x01, 0x71, 0x8a, 0x01, 0x05, 0x8b, 0x03, 0x2f, 0x06, 0x01,
                       0xc6, 0x09, 0x90, 0x01, 0x80 if DF.pin_enabled else 0x00, 0x83, 0x01, 0x01, 0x83, 0x01, 0x81])  # PS_DO: PIN1 enabled/disabled
        return bytes([0x62, len(body)]) + body


def build_filesystem(imsi, iccid='8939990000000000010', msisdn=None, spn='H3G', alpha='Il mio numero'):
    # UST: services 19 (SPN) and 21 (MSISDN) are declared in byte 3 (0x04 | 0x10)
    ust = bytes([0x9e, 0x1e, 0x14, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    usim = DF(0x7fff, 'ADF', USIM_AID, [
        EF(0x6f07, imsi_bytes(imsi), sfi=7),
        EF(0x6f78, bytes([0x00, 0x01]), sfi=6),
        EF(0x6f7e, bytes([0x12, 0x34, 0x56, 0x78, 0x22, 0xf2, 0x99, 0x00, 0x01, 0xff, 0x00]), sfi=0x0b),
        EF(0x6f73, bytes([0x87, 0x65, 0x43, 0x21, 0xff, 0xff, 0xff, 0x22, 0xf2, 0x99, 0x00, 0x01, 0x00, 0x00]), sfi=0x0c),
        EF(0x6fad, bytes([0x00, 0x00, 0x00, 0x02]), sfi=3),
        EF(0x6f38, ust, sfi=4),
        EF(0x6f31, bytes([0x0a]), sfi=0x12),
        EF(0x6f46, bytes([0x00]) + spn.encode('latin-1')[:16].ljust(16, b'\xff'), sfi=0x0f),
        EF(0x6f40, records=[msisdn_record(msisdn or '', alpha)], record_length=28),
        EF(0x6f05, b'it\xff\xff', sfi=2),
        EF(0x6f7b, bytes([0xff] * 12), sfi=0x0d),
        EF(0x6f3e, bytes([0xff] * 4)), EF(0x6f3f, bytes([0xff] * 4)),
        EF(0x6f5b, bytes([0xff] * 6)), EF(0x6f5c, bytes([0x00, 0x00, 0x00])),
        EF(0x6f08, bytes([0xff] * 32 + [0x07]), sfi=8),
        EF(0x6f09, bytes([0xff] * 32 + [0x07]), sfi=9),
        EF(0x6f43, bytes([0xff, 0xff])),
        EF(0x6fb7, records=[bytes([0xff] * 4)]),
        EF(0x6f42, records=[bytes([0xff] * 28 + [0x00, 0x00, 0x00, 0x00])]),
        EF(0x6f3c, records=[bytes([0x00] + [0xff] * 175)] * 10),
    ])
    telecom = DF(0x7f10, 'DF', None, [EF(0x6f3a, records=[bytes([0xff] * 28)] * 10)])
    mf = DF(0x3f00, 'MF', None, [
        EF(0x2f00, records=[b'\xff' * 0x21], sfi=0x1e, record_length=0x21),
        EF(0x2fe2, bcd_swap(iccid).ljust(10, b'\xff')[:10], sfi=2),
        EF(0x2f05, b'it\xff\xff', sfi=5),
        EF(0x2f06, records=[bytes.fromhex('800101a406830101950108'), bytes.fromhex('800101900080012a8401d4'),
                            bytes.fromhex('800103a406830101950108')], sfi=0x06, record_length=0x0b),
        telecom,
        usim,
    ])
    # EF_DIR record: 61 len 4F len AID 50 len label; padded to 0x21 bytes.
    label = b'USIM'
    record = bytes([0x61, 4 + len(USIM_AID) + 2 + len(label), 0x4f, len(USIM_AID)]) + USIM_AID + bytes([0x50, len(label)]) + label
    mf.children[0x2f00].records = [bytearray(record.ljust(0x21, b'\xff'))]
    mf.children[0x2f00].record_length = 0x21
    return mf


class UsimCard:
    def __init__(self, imsi='222990000000001', pin_prompt=True, pin='0000', profile=None, state_path=None):
        """profile: dict from sim_profile (identity); state_path: JSON file where phone writes are persisted."""
        profile = profile or {}
        self.strict_read_length = False  # enabled by the experimental U880 transport
        self.imsi = profile.get('imsi', imsi)
        self.pin_prompt = pin_prompt
        DF.pin_enabled = pin_prompt
        self.pin = profile.get('pin', pin).encode() if isinstance(profile.get('pin', pin), str) else pin
        self.puk = profile.get('puk', '12345678')
        self.mf = build_filesystem(self.imsi, profile.get('iccid', '8939990000000000010'), profile.get('msisdn'),
                                   profile.get('spn', 'H3G'), profile.get('alpha', 'Il mio numero'))
        self.current_df = self.mf
        self.current_ef = None
        self.parent = {id(self.mf): None}
        stack = [self.mf]
        while stack:
            parent = stack.pop()
            for child in parent.children.values():
                self.parent[id(child)] = parent
                if isinstance(child, DF):stack.append(child)
        self.pending = bytearray()      # response data waiting for GET RESPONSE
        self.buffer = bytearray()
        self.waiting_data = None        # (header, length) while collecting command data
        self.pin_verified = not pin_prompt
        self.apdus = []
        self.pps = []
        self.state_path = state_path
        self.dirty = set()
        self.load_state()

    # --- persistence of what the phone writes -------------------------------------------------
    def ef_paths(self):
        """(path, ef) for every EF, path = hex file ids from the MF, e.g. '3f00/7fff/6f3a'."""
        stack = [('3f00', self.mf)]
        while stack:
            path, node = stack.pop()
            for child in node.children.values():
                child_path = f'{path}/{child.fid:04x}'
                if isinstance(child, DF):
                    stack.append((child_path, child))
                else:
                    yield child_path, child

    def load_state(self):
        import json
        if not self.state_path:
            return
        try:
            saved = json.loads(open(self.state_path).read())
        except (OSError, ValueError):
            return
        for path, ef in self.ef_paths():
            entry = saved.get('files', {}).get(path)
            if not entry:
                continue
            if ef.structure == 'transparent' and 'data' in entry:
                ef.data = bytearray.fromhex(entry['data'])
            elif ef.structure != 'transparent' and 'records' in entry:
                ef.records = [bytearray.fromhex(r) for r in entry['records']]
            self.dirty.add(path)

    def save_state(self):
        import json
        import os
        if not self.state_path:
            return
        files = {}
        for path, ef in self.ef_paths():
            if path in self.dirty:
                files[path] = ({'data': bytes(ef.data).hex()} if ef.structure == 'transparent'
                               else {'records': [bytes(r).hex() for r in ef.records]})
        os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
        temporary = str(self.state_path) + '.tmp'
        with open(temporary, 'w') as handle:
            json.dump({'files': files}, handle)
        os.replace(temporary, self.state_path)

    def mark_written(self, ef):
        for path, candidate in self.ef_paths():
            if candidate is ef:
                self.dirty.add(path)
                self.save_state()
                return

    def reset(self):
        """Warm/cold reset: back to the MF, no pending command, no partial bytes."""
        self.pin_verified = not self.pin_prompt
        self.current_df, self.current_ef = self.mf, None
        self.pending = bytearray()
        self.buffer = bytearray()
        self.waiting_data = None

    def find_by_fid(self, fid):
        stack = [self.mf]
        while stack:
            node = stack.pop()
            if node.fid == fid:
                return node
            if isinstance(node, DF):
                stack.extend(node.children.values())
        return None

    def snapshot(self):
        return {'df': self.current_df.fid, 'ef': self.current_ef.fid if self.current_ef else None,
                'pin_verified': self.pin_verified, 'pending': bytes(self.pending).hex(),
                'buffer': bytes(self.buffer).hex(),
                'waiting': [self.waiting_data[0].hex(), self.waiting_data[1]] if self.waiting_data else None}

    def load(self, snap):
        self.current_df = self.find_by_fid(snap['df']) or self.mf
        self.current_ef = self.find_by_fid(snap['ef']) if snap['ef'] is not None else None
        self.pin_verified = snap['pin_verified']
        self.pending = bytearray.fromhex(snap['pending'])
        self.buffer = bytearray.fromhex(snap['buffer'])
        self.waiting_data = (bytes.fromhex(snap['waiting'][0]), snap['waiting'][1]) if snap['waiting'] else None

    # --- T=0 byte level ------------------------------------------------------------------
    @staticmethod
    def pps_length(buffer):
        if len(buffer) < 2:
            return None
        return 3 + sum(1 for bit in (0x10, 0x20, 0x40) if buffer[1] & bit)

    def receive(self, byte):
        """One byte from the terminal. Returns bytes the card sends back after it."""
        self.buffer.append(byte)
        if self.waiting_data is not None:
            header, length = self.waiting_data
            if len(self.buffer) >= length:
                data = bytes(self.buffer[:length])
                self.buffer.clear()
                self.waiting_data = None
                return self.run(header, data)
            return b''
        if self.buffer[0] == 0xff:  # PPS request (a header never starts with 0xFF): echo when complete
            need = self.pps_length(self.buffer)
            if need is not None and len(self.buffer) >= need:
                request = bytes(self.buffer)
                self.buffer.clear()
                self.pps.append(request)
                return request
            return b''
        if len(self.buffer) < 5:
            return b''
        header = bytes(self.buffer[:5])
        self.buffer.clear()
        cla, ins, p1, p2, p3 = header
        if ins in DATA_IN and p3:
            self.waiting_data = (header, p3)
            return bytes([ins])  # procedure byte: send the data now
        return self.run(header, b'')

    def run(self, header, data):
        cla, ins, p1, p2, p3 = header
        status, out = self.apdu(cla, ins, p1, p2, p3, data)
        self.apdus.append((header.hex(), data.hex(), out.hex()[:40], '%04x' % status))
        # Case 2 commands send a procedure byte (INS) before the data, then the status words.
        procedure = bytes([ins]) if out else b''
        return procedure + out + bytes([status >> 8, status & 0xff])

    # --- APDU level ----------------------------------------------------------------------
    def apdu(self, cla, ins, p1, p2, p3, data):
        if cla not in (0x00, 0x80, 0x01, 0x02, 0x03, 0x40, 0x41, 0x42, 0x43):
            return 0x6e00, b''  # class not supported: makes the driver fall back to GSM commands
        handler = {0xa4: self.select, 0xc0: self.get_response, 0xb0: self.read_binary,
                   0xb2: self.read_record, 0xf2: self.status, 0x20: self.verify, 0x10: self.terminal_profile,
                   0xd6: self.update_binary, 0xdc: self.update_record, 0x70: self.manage_channel,
                   0xc2: self.envelope, 0x14: self.terminal_response, 0x12: self.fetch,
                   0xa2: self.search_record, 0x24: self.pin_other, 0x26: self.pin_other,
                   0x28: self.pin_other, 0x2c: self.unblock_pin}.get(ins)
        if handler is None:
            return 0x6d00, b''
        return handler(p1, p2, p3, data)

    def find(self, fid):
        node = self.current_df
        if fid == 0x3f00:
            return self.mf
        if fid in node.children:
            return node.children[fid]
        if fid == self.current_df.fid:
            return self.current_df
        if self.current_ef is None and fid in self.mf.children and self.current_df is not self.mf:
            pass
        # Sibling of the current EF, or child of MF.
        if fid in self.mf.children:
            return self.mf.children[fid]
        return None

    def select(self, p1, p2, p3, data):
        node = None
        if p1 == 0x04:  # by DF name (AID)
            for child in self.mf.children.values():
                if getattr(child, 'aid', None) and (child.aid.startswith(data) or data.startswith(child.aid[:len(data)])):
                    node = child
            if node is None:
                return 0x6a82, b''
        elif p1 in (0x08, 0x09):  # by path from MF / current DF
            node = self.mf if p1 == 0x08 else self.current_df
            for i in range(0, len(data), 2):
                fid = (data[i] << 8) | data[i + 1]
                if fid == 0x3f00 and i == 0:
                    node = self.mf
                    continue
                child = node.children.get(fid) if isinstance(node, DF) else None
                if child is None:
                    return 0x6a82, b''
                node = child
        elif p1 == 0x00 and len(data) == 2:  # by file identifier
            node = self.find((data[0] << 8) | data[1])
            if node is None:
                return 0x6a82, b''
        elif p1 == 0x00 and not data:
            node = self.mf
        else:
            return 0x6a86, b''
        if isinstance(node, DF):
            self.current_df, self.current_ef = node, None
        else:
            self.current_ef = node
            self.current_df = self.parent[id(node)]
        fcp = node.fcp()
        if p2 & 0x0c == 0x0c:
            self.pending = bytearray()
            return 0x9000, b''
        self.pending = bytearray(fcp)
        return 0x6100 | len(fcp), b''

    def get_response(self, p1, p2, p3, data):
        out = bytes(self.pending[:p3 or 256])
        self.pending = bytearray()
        return 0x9000, out

    def read_binary(self, p1, p2, p3, data):
        ef = self.current_ef
        if ef is None or ef.structure != 'transparent':
            return 0x6986, b''
        offset = (p1 << 8) | p2
        if p1 & 0x80:  # short EF identifier
            sfi = p1 & 0x1f
            for child in list(self.current_df.children.values()) + list(self.mf.children.values()):
                if isinstance(child, EF) and child.sfi == sfi:
                    ef, offset = child, p2
                    self.current_ef = child
                    break
            else:
                return 0x6a82, b''
        if offset > len(ef.data):
            return 0x6b00, b''
        length = p3 or 256
        remaining = len(ef.data)-offset
        if self.strict_read_length and length > remaining:
            # T=0 cannot signal early SW while the terminal still expects data.
            # Return the exact available Le so the terminal can retry.
            return (0x6c00 | remaining, b'') if 0 < remaining < 256 else (0x6282, b'')
        return 0x9000, bytes(ef.data[offset:offset + length])

    def read_record(self, p1, p2, p3, data):
        ef = self.current_ef
        sfi = p2 >> 3
        if sfi:
            for child in list(self.current_df.children.values()) + list(self.mf.children.values()):
                if isinstance(child, EF) and child.sfi == sfi:
                    ef = self.current_ef = child
                    break
            else:
                return 0x6a82, b''
        if ef is None or ef.structure == 'transparent':
            return 0x6986, b''
        if p1 == 0 or p1 > len(ef.records):
            return 0x6a83, b''
        record = bytes(ef.records[p1 - 1])
        if p3 and p3 != len(record):
            return 0x6c00 | len(record), b''
        return 0x9000, record

    def search_record(self, p1, p2, p3, data):
        """SEARCH RECORD (TS 102 221 11.1.7), simple search on the current linear EF."""
        ef = self.current_ef
        if ef is None or ef.structure == 'transparent':
            return 0x6986, b''
        mode = p2 & 0x07
        total = len(ef.records)
        start = p1 if p1 else 1
        if mode == 4:      # forward, starting with record P1
            order = list(range(start, total + 1))
        elif mode == 6:    # forward, starting with the record after the current one
            order = list(range(start + 1, total + 1)) if p1 else list(range(1, total + 1))
            order = list(range(1, total + 1)) if not order and p1 == 1 and total == 1 else order
            if p1 == 1 and total >= 1:
                order = list(range(1, total + 1))  # the driver starts with P1=1 and expects record 1 to be found
        elif mode == 5:    # backward from the last record
            order = list(range(total, 0, -1))
        else:              # backward from the record before the current one
            order = list(range(start - 1, 0, -1))
        # Enhanced search: first byte = search indication (0x01 from the start, 0x04 from the offset in
        # the second byte), the rest is the pattern. Anything else is a simple search.
        indication, pattern, offset = None, data, None
        if len(data) > 2 and data[0] in (0x01, 0x04):
            indication = data[0]
            offset, pattern = (data[1], data[2:]) if indication == 0x04 else (0, data[1:])
        found = bytes(n for n in order
                      if (pattern in bytes(ef.records[n - 1]) if offset is None
                          else bytes(ef.records[n - 1][offset:offset + len(pattern)]) == pattern))
        if not found:
            return 0x6a83, b''
        self.pending = bytearray(found)
        return 0x6100 | len(found), b''

    def status(self, p1, p2, p3, data):
        fcp = self.current_df.fcp()
        if p2 == 0x0c:
            return 0x9000, b''
        return 0x9000, fcp[:p3 or len(fcp)]

    def verify(self, p1, p2, p3, data):
        # No data = query: PIN1 is enabled and not yet verified, 3 attempts left.
        if not p3:
            # Remaining attempts are reported even when PIN1 is disabled (PS_DO tells the phone not to ask).
            return (0x9000, b'') if self.pin_verified and self.pin_prompt else (0x63c3, b'')
        self.pin_verified = data[:len(self.pin)] == self.pin
        return (0x9000, b'') if self.pin_verified else (0x63c2, b'')

    def pin_other(self, p1, p2, p3, data):
        return 0x9000, b''  # change/disable/enable PIN: accepted without state

    def unblock_pin(self, p1, p2, p3, data):
        # RESET RETRY COUNTER with no data is a status query: 10 PUK attempts left.
        return (0x63ca, b'') if not p3 else (0x9000, b'')

    def terminal_profile(self, p1, p2, p3, data):
        self.apdus_profile = data
        return 0x9000, b''

    def terminal_response(self, p1, p2, p3, data):
        return 0x9000, b''

    def fetch(self, p1, p2, p3, data):
        return 0x6700, b''

    def envelope(self, p1, p2, p3, data):
        return 0x9000, b''

    def update_binary(self, p1, p2, p3, data):
        ef = self.current_ef
        if ef is None or ef.structure != 'transparent':
            return 0x6986, b''
        offset = (p1 << 8) | p2
        ef.data[offset:offset + len(data)] = data
        self.mark_written(ef)
        return 0x9000, b''

    def update_record(self, p1, p2, p3, data):
        ef = self.current_ef
        if ef is None or ef.structure == 'transparent' or not 0 < p1 <= len(ef.records):
            return 0x6a83, b''
        ef.records[p1 - 1][:] = data.ljust(ef.record_length, b'\xff')[:ef.record_length]
        self.mark_written(ef)
        return 0x9000, b''

    def manage_channel(self, p1, p2, p3, data):
        if p1 == 0x00:
            return 0x9000, b'\x01'  # only the basic channel is really modelled
        return 0x9000, b''
