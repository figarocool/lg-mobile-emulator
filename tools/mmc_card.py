"""SD memory card (up to 2 GB, byte addressed) backed by an image file. Protocol level only: SD Physical Layer 1.x."""
import os
import struct

BLOCK = 512
OCR_READY = 0x80ff8000

IDLE, READY, IDENT, STBY, TRAN, DATA, RCV, PRG = 0, 1, 2, 3, 4, 5, 6, 7


def crc7(data):
    crc = 0
    for byte in data:
        for bit in range(8):
            crc = ((crc << 1) ^ (0x09 if (crc >> 6) ^ ((byte >> (7 - bit)) & 1) else 0)) & 0x7f
    return crc


def r1_bytes(index, status):
    body = bytes([index & 0x3f]) + struct.pack('>I', status)
    return body + bytes([(crc7(body) << 1) | 1])


def r3_bytes(ocr):
    return bytes([0x3f]) + struct.pack('>I', ocr) + b'\xff'


def csd_for(size_bytes):
    """CSD version 1.0 for a standard-capacity card of this size (TS SD Physical Layer 5.3.2)."""
    blocks = size_bytes // BLOCK
    read_bl_len = 9
    # blocks = (C_SIZE + 1) * 2^(C_SIZE_MULT + 2)
    mult = 7
    c_size = max(1, blocks // (1 << (mult + 2)) - 1)
    while c_size > 0xfff and mult > 0:
        mult -= 1
        c_size = max(1, blocks // (1 << (mult + 2)) - 1)
    csd = bytearray(16)
    csd[0] = 0x00                              # CSD_STRUCTURE 0
    csd[1] = 0x0e                              # TAAC
    csd[2] = 0x00                              # NSAC
    csd[3] = 0x32                              # TRAN_SPEED 25 MHz
    csd[4] = 0x5b                              # CCC
    csd[5] = 0x50 | read_bl_len                # CCC low nibble, READ_BL_LEN
    csd[6] = 0x80 | (c_size >> 10)             # READ_BL_PARTIAL, C_SIZE[11:10]
    csd[7] = (c_size >> 2) & 0xff
    csd[8] = ((c_size & 3) << 6) | 0x3f        # C_SIZE[1:0], VDD_R_CURR_MIN/MAX
    csd[9] = 0xfc | (mult >> 1)                # VDD_W, C_SIZE_MULT[2:1]
    csd[10] = ((mult & 1) << 7) | 0x40 | 0x3f  # C_SIZE_MULT[0], ERASE_BLK_EN, SECTOR_SIZE
    csd[11] = 0x80                             # WP_GRP_SIZE 0, WP_GRP_ENABLE 1
    csd[12] = 0x0a                             # R2W_FACTOR 2, WRITE_BL_LEN[3:2]
    csd[13] = 0x40 | 0x00                      # WRITE_BL_LEN[1:0] = 1 (512)
    csd[14] = 0x00
    csd[15] = (crc7(bytes(csd[:15])) << 1) | 1
    return bytes(csd)


def cid_for(name='U310EMU'):
    cid = bytearray(16)
    cid[0] = 0x1d                              # manufacturer id (fictional)
    cid[1:3] = b'EM'
    cid[3:8] = name.encode('ascii')[:5].ljust(5, b' ')
    cid[8] = 0x10                              # product revision
    cid[9:13] = struct.pack('>I', 0x31000001)  # serial number
    cid[13] = 0x00
    cid[14] = 0x6a                             # manufacturing date
    cid[15] = (crc7(bytes(cid[:15])) << 1) | 1
    return bytes(cid)


class SdCard:
    def __init__(self, path):
        self.path = path
        self.file = open(path, 'r+b')
        self.size = os.path.getsize(path)
        self.csd, self.cid = csd_for(self.size), cid_for()
        self.rca = 0x1234
        self.reset()

    def reset(self):
        self.state = IDLE
        self.app_command = False
        self.block_length = BLOCK
        self.initialised = False
        self.writes = 0
        self.reads = 0

    def close(self):
        self.file.close()

    def finish_transfer(self):
        if self.state in (DATA, RCV, PRG):
            self.state = TRAN

    def status(self):
        return (self.state << 9) | (1 << 8)    # current state, READY_FOR_DATA

    # -- commands -----------------------------------------------------------------------------------------------
    def command(self, index, argument):
        """Returns (response_bytes or None for no response, kind) where kind describes follow-up data."""
        app = self.app_command
        self.app_command = False
        if index == 0:
            self.reset()
            return None, None
        if index == 55:
            self.app_command = True
            return r1_bytes(55, self.status() | (1 << 5)), None
        if app and index == 41:
            if self.state == IDLE:
                self.state = READY if argument & 0x00ff8000 else IDLE
            return r3_bytes(OCR_READY), None
        if index == 2 and self.state in (READY, IDENT):
            self.state = IDENT
            return bytes([0x3f]) + self.cid, None
        if index == 3 and self.state in (IDENT, STBY):
            self.state = STBY
            return r1_bytes(3, (self.rca << 16) | 0x0500), None   # R6: RCA and short status
        if index == 9:
            return bytes([0x3f]) + self.csd, None
        if index == 7:
            self.state = TRAN if (argument >> 16) == self.rca else STBY
            return r1_bytes(7, self.status()), None
        if index == 13:
            return r1_bytes(13, self.status()), None
        if index == 16:
            self.block_length = argument or BLOCK
            return r1_bytes(16, self.status()), None
        if index == 17 or index == 18:
            self.read_position = argument
            self.state = DATA
            return r1_bytes(index, self.status()), ('read', index == 18)
        if index == 24 or index == 25:
            self.write_position = argument
            self.state = RCV
            return r1_bytes(index, self.status()), ('write', index == 25)
        if index == 12:
            self.state = TRAN
            return r1_bytes(12, self.status()), None
        if app and index == 6:
            return r1_bytes(6, self.status()), None
        if app and index == 51:
            self.state = DATA
            return r1_bytes(51, self.status()), ('scr', False)
        if app and index == 13:
            self.state = DATA
            return r1_bytes(13, self.status()), ('sdstatus', False)
        if index == 1 or index == 8:
            return None, None                                       # MMC op cond / SD 2.0: not for this card
        return r1_bytes(index, self.status() | 0x00400000), None   # ILLEGAL_COMMAND

    # -- data ---------------------------------------------------------------------------------------------------
    def read_block(self):
        self.file.seek(self.read_position)
        data = self.file.read(BLOCK).ljust(BLOCK, b'\0')
        self.read_position += BLOCK
        self.reads += 1
        return data

    def scr(self):
        return bytes([0x00, 0x25, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])   # SD 1.01, 1 and 4 bit buses

    def sd_status(self):
        return bytes(64)

    def write_block(self, data):
        self.file.seek(self.write_position)
        self.file.write(data)
        self.file.flush()
        self.write_position += BLOCK
        self.writes += 1
