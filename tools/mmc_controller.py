"""Memory card controller at 0x61800000 with an SD card behind it.

Register map recovered from the original driver (mmc_init_real and the sector read/write functions):
  +0x00 clock control (1: start, 2: stop)        +0x04 status
  +0x14 status clear                              +0x18, +0x08, +0x20 configuration
  +0x28 command (0x40 | index)                    +0x2c / +0x30 argument high / low 16 bits
  +0x10 control: writing it sends the command (0x40: no response, 1: R1, 3: R3, 5: R1 + data read ...)
  +0x34 response FIFO, 16 bits per read, first byte (the command index) in the high half
  +0x38 data FIFO,     16 bits per access, first byte in the high half
Status bits used by the driver: 0x100 clock running, 0x2000 command done, 0x80 data FIFO ready, bits 5:0 errors.
Without a card the model is the plain clock model (mmc_clock.MmcClock): commands never complete and the driver
gives up, exactly as on a phone with no card inserted.
"""
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE

from mmc_clock import MmcClock
from mmc_card import BLOCK

STATUS, CLEAR, COMMAND, ARG_HIGH, ARG_LOW, CONTROL, RESPONSE, DATA = 0x04, 0x14, 0x28, 0x2c, 0x30, 0x10, 0x34, 0x38
DONE, FIFO_READY, TIMEOUT, CLOCK = 0x2000, 0x80, 0x04, 0x100
DETECT = 0x8400016c          # GPIO input word: bit 3 is the card-detect switch read by mmc_exist() at 0x36670c
DETECT_BIT = 1 << 3


class MmcController(MmcClock):
    def __init__(self, card=None):
        super().__init__()
        self.card = card
        self.registers = {}
        self.response = []          # 16-bit words waiting in the response FIFO
        self.data_out = []          # 16-bit words the phone will read (card -> phone)
        self.data_in = bytearray()  # bytes the phone writes (phone -> card)
        self.pending = None         # ('read'|'write'|'scr'|'sdstatus', multi)
        self.commands = []
        self.groups = []
        self.status_log = []
        self.words_read = 0
        self.blocks_left = 0
        self.words_by_command = []
        self.trace = []

    def attach(self, uc):
        super().attach(uc)
        self.uc = uc
        import os
        self.active_low = os.environ.get('U310_SD_DETECT') == 'low'
        if self.card:
            word = self.detect_word(int.from_bytes(uc.mem_read(DETECT, 4), 'little'))
            uc.mem_write(DETECT, word.to_bytes(4, 'little'))
            uc.hook_add(UC_HOOK_MEM_READ, self.detect, begin=DETECT, end=DETECT + 3)
            uc.hook_add(UC_HOOK_MEM_WRITE, self.write, begin=self.BASE + 0x08, end=self.BASE + 0x3f)
            uc.hook_add(UC_HOOK_MEM_READ, self.read, begin=self.BASE + STATUS, end=self.BASE + STATUS + 3)
            uc.hook_add(UC_HOOK_MEM_READ, self.read, begin=self.BASE + RESPONSE, end=self.BASE + DATA + 3)

    def detect_word(self, word):
        return word & ~DETECT_BIT if self.active_low else word | DETECT_BIT

    def detect(self, uc, access, address, size, value, _):
        word = self.detect_word(int.from_bytes(uc.mem_read(DETECT, 4), 'little'))
        uc.mem_write(DETECT, word.to_bytes(4, 'little'))

    # -- helpers --------------------------------------------------------------------------------------------------
    def status(self):
        return int.from_bytes(self.uc.mem_read(self.BASE + STATUS, 4), 'little')

    def set_status(self, value):
        self.uc.mem_write(self.BASE + STATUS, (value & 0xffffffff).to_bytes(4, 'little'))

    @staticmethod
    def words(data):
        data = bytes(data) + (b'\0' if len(data) % 2 else b'')
        return [(data[i] << 8) | data[i + 1] for i in range(0, len(data), 2)]

    def load_block(self):
        kind, multi = self.pending
        if kind == 'read':
            self.data_out = self.words(self.card.read_block())
        elif kind == 'scr':
            self.data_out = self.words(self.card.scr())
        else:
            self.data_out = self.words(self.card.sd_status())

    # -- register access ------------------------------------------------------------------------------------------
    def write(self, uc, access, address, size, value, _):
        offset = address - self.BASE
        self.registers[offset] = value
        if offset == CLEAR:
            self.set_status(self.status() & ~(value & 0xff) & ~(DONE if value & 0x100 else 0))
        elif offset == CONTROL:
            self.send_command(value)
        elif offset == DATA:
            self.receive_word(value & 0xffff)

    def send_command(self, control):
        index = self.registers.get(COMMAND, 0) & 0x3f
        argument = (self.registers.get(ARG_HIGH, 0) << 16) | self.registers.get(ARG_LOW, 0)
        status = self.status() & ~(DONE | FIFO_READY | 0x3f)
        self.words_by_command.append(self.words_read)
        self.words_read = 0
        self.trace = []
        self.response, self.data_out, self.data_in, self.pending = [], [], bytearray(), None
        response, follow = self.card.command(index, argument)
        entry = (index, argument, None if response is None else response.hex()[:12])
        if self.groups and self.groups[-1][0] == entry:
            self.groups[-1][1] += 1
        else:
            self.groups.append([entry, 1])
        self.commands.append(entry)
        if response is not None:
            self.response = self.words(response)
        elif index != 0 and not control & 0x40:
            status |= TIMEOUT                       # the host waited for an answer that never came
        self.pending = follow
        self.blocks_left = max(1, self.registers.get(0x20, 1)) if follow else 0   # +0x20: block count
        if follow and follow[0] != 'write':
            self.load_block()
            self.blocks_left -= 1
        self.set_status(status | DONE)

    def read(self, uc, access, address, size, value, _):
        offset = address - self.BASE
        if offset == STATUS:
            status = self.status() & ~FIFO_READY
            if self.data_out:
                status |= FIFO_READY
            elif self.pending and self.pending[0] == 'write':
                status |= FIFO_READY                # room for the next word to send
            self.set_status(status)
            self.trace.append(('S', hex(status), len(self.data_out)))
            if len(self.status_log) < 400:
                self.status_log.append((hex(status), len(self.data_out), self.pending and self.pending[0]))
        elif offset == RESPONSE:
            word = self.response.pop(0) if self.response else 0
            uc.mem_write(address, word.to_bytes(4, 'little'))
        elif offset == DATA:
            word = self.data_out.pop(0) if self.data_out else 0
            self.words_read += 1
            self.trace.append(('D', len(self.data_out)))
            uc.mem_write(address, word.to_bytes(4, 'little'))
            if not self.data_out and self.pending:
                if self.pending[0] == 'read' and self.pending[1] and self.blocks_left > 0:
                    self.load_block()                # multiple block read: the next block follows at once
                    self.blocks_left -= 1
                else:
                    self.card.finish_transfer()      # single block / register read complete: card back to transfer state

    def receive_word(self, word):
        if not self.pending or self.pending[0] != 'write':
            return
        self.data_in += bytes([word >> 8, word & 0xff])
        if len(self.data_in) >= BLOCK:
            self.card.write_block(bytes(self.data_in[:BLOCK]))
            self.data_in = bytearray(self.data_in[BLOCK:])
            self.blocks_left -= 1
            if not self.pending[1] or self.blocks_left <= 0:
                self.card.finish_transfer()

    def report(self):
        data = super().report()
        data.update({'card': bool(self.card), 'commands': self.commands[-40:], 'groups': [[list(e), n] for e, n in self.groups[:120]], 'status_log': self.status_log[-10:], 'words_by_command': self.words_by_command[-30:], 'last_words': self.words_read, 'trace_tail': self.trace[-60:],
                     'reads': getattr(self.card, 'reads', 0), 'writes': getattr(self.card, 'writes', 0)})
        return data
