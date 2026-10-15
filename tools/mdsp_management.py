"""Experimental HLE for one MDSP management mailbox, not a DSP interpreter.

AMSS 0x482b12 submits command 1 and a module mask; 0x48288c expects
the command cleared and the returned mask equal to the requested mask.
IRQ source 5 invokes 0x482590 with index 1; the image's byte at
0x568c08 selects index 1 for 0x4828d0 -> 0x48288c.
Successful module activation is an explicit HLE assumption. No DSP module
instructions, signal processing or baseband work are executed by this model.
The inferred reset/release sequence also supplies a boot-ready halfword
at the original ARM driver's first read after loading the image.
"""
from collections import Counter
from unicorn import UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ


class MdspManagement:
    DOORBELL = 0x50c00008
    COMMAND = 0x50206310
    REQUEST_MASK = 0x5040b380
    RESPONSE_MASK = 0x5040b37c
    IRQ = 5
    CONTROL = 0x50c00010
    BOOT_STATUS = 0x5020625a
    WCDMA_READY = 0x50001faa  # l1m.c polls this byte (0x892954) after the WCDMA module is enabled

    def __init__(self, uc, interrupts, qdsp=False):
        self.uc = uc
        self.interrupts = interrupts
        self.doorbell = False
        import os
        from qdsp_model import QdspModel
        self.qdsp = QdspModel(uc, interrupts) if qdsp or os.environ.get('U310_QDSP_IRQ') else None
        self.completed = Counter()
        self.unsupported = Counter()
        self.reset_seen = False
        self.boot_pending = False
        self.boot_replies = 0
        uc.hook_add(UC_HOOK_MEM_WRITE, self.write,
                    begin=self.DOORBELL, end=self.DOORBELL+3)
        uc.hook_add(UC_HOOK_MEM_WRITE, self.control,
                    begin=self.CONTROL, end=self.CONTROL+3)
        import os
        if not os.environ.get('U310_NO_WCDMA_READY'):
            uc.hook_add(UC_HOOK_MEM_READ, self.wcdma_ready, begin=self.WCDMA_READY, end=self.WCDMA_READY)
        uc.hook_add(UC_HOOK_MEM_READ, self.boot_status,
                    begin=self.BOOT_STATUS, end=self.BOOT_STATUS+1)

    def control(self, uc, access, address, size, value, _):
        # Original 0x4824cc writes 0x1b then 0x3b before copying microcode.
        if address == self.CONTROL and size == 4:
            if value == 0x1b:
                self.reset_seen = True
                self.boot_pending = False
            elif value == 0x3b and self.reset_seen:
                self.reset_seen = False
                self.boot_pending = True

    def boot_status(self, uc, access, address, size, value, _):
        # 0x482848 tests this halfword after loading; zero enters recovery.
        # Delay until the read so the preceding image copy cannot erase it.
        if address == self.BOOT_STATUS and size == 2 and self.boot_pending:
            uc.mem_write(address, b'\x01\x00')
            self.boot_pending = False
            self.boot_replies += 1

    def wcdma_ready(self, uc, access, address, size, value, _):
        uc.mem_write(self.WCDMA_READY, b'\x01')

    def write(self, uc, access, address, size, value, _):
        if address == self.DOORBELL and size == 4:
            self.doorbell = True

    def initialize_after_restore(self):
        # Resume only a command already submitted by the original ARM code.
        self.doorbell = self.command() != 0
        self.boot_pending = int.from_bytes(self.uc.mem_read(self.CONTROL, 4), 'little') == 0x3b

    def command(self):
        return int.from_bytes(self.uc.mem_read(self.COMMAND, 2), 'little')

    def advance(self):
        if self.qdsp:
            self.qdsp.advance()
        if not self.doorbell:
            return
        self.doorbell = False
        command = self.command()
        if command == 0:
            return
        if command != 1:
            self.unsupported[command] += 1
            return
        mask = bytes(self.uc.mem_read(self.REQUEST_MASK, 4))
        self.uc.mem_write(self.RESPONSE_MASK, mask)
        self.uc.mem_write(self.COMMAND, b'\x00\x00')
        self.interrupts.raise_source(self.IRQ)
        self.completed[command] += 1

    def report(self):
        return {'kind': 'experimental high-level MDSP management response',
                'qdsp': self.qdsp.report() if self.qdsp else None, 'completed': dict(self.completed), 'unsupported': dict(self.unsupported),
                'command': self.command(), 'irq_source': self.IRQ,
                'boot_replies': self.boot_replies,
                'executes_dsp_code': False,
                'limitations': ['command 1 module-mask acknowledgement and boot-ready status only',
                                'activation succeeds by HLE assumption',
                                'no DSP instructions, audio or baseband execution',
                                'completion timing not cycle accurate']}
