"""Experimental model of the audio QDSP's service interrupt (IRQ 10).

The ARM driver (qdsptask.c) forwards IRQ 10 to the ISR of every enabled QDSP app; the vocoder
app's ISR (0x126a23a) reads a status halfword the DSP firmware would have written. The DSP code is
not executed: after the image descriptor is written (boot), this model raises the interrupt on a
fixed 20 ms frame period and the firmware's reaction is observed/answered here.
"""
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE


class SbiBus:
    """Serial Bus Interface (0x84000d00): register bus of the PMIC and the audio codec (Adie).

    Protocol recovered from the ARM driver (0x15914d8 write, 0x159156a read):
      +0x04  slave address (low 6 bits), +0x10  one word per byte: bit15 = read, bits 14:8 = register,
      bits 7:0 = data to write; the transfer is started by pulsing +0x20 and ends when +0x2c bit 0 is set.
      Read results appear in +0x14 (1 byte), +0x18/+0x14 (2 bytes) or +0x1c/+0x18/+0x14 (3 bytes).
    The model keeps a register file per slave and completes every transfer at once.
    """
    BASE = 0x84000d00
    ADDRESS, DATA, START, DONE = BASE + 0x04, BASE + 0x10, BASE + 0x20, BASE + 0x2c
    RESULTS = (BASE + 0x14, BASE + 0x18, BASE + 0x1c)

    def __init__(self, uc):
        self.uc = uc
        self.registers = {}
        self.queue = []
        self.transfers = 0
        uc.hook_add(UC_HOOK_MEM_WRITE, self.data, begin=self.DATA, end=self.DATA + 3)
        uc.hook_add(UC_HOOK_MEM_WRITE, self.start, begin=self.START, end=self.START + 3)

    def slave(self):
        return int.from_bytes(self.uc.mem_read(self.ADDRESS, 4), 'little') & 0x3f

    def data(self, uc, access, address, size, value, _):
        self.queue.append(value & 0xffff)

    def start(self, uc, access, address, size, value, _):
        if not value & 1:
            return
        bank = self.registers.setdefault(self.slave(), {})
        reads = []
        for word in self.queue:
            register = (word >> 8) & 0x7f
            if word & 0x8000:
                reads.append(bank.get(register, 0))
            else:
                bank[register] = word & 0xff
        self.queue = []
        for slot, byte in zip(self.RESULTS, reversed(reads)):
            uc.mem_write(slot, byte.to_bytes(4, 'little'))
        uc.mem_write(self.DONE, (1).to_bytes(4, 'little'))
        self.transfers += 1


class QdspModel:
    DESCRIPTOR = 0x58401000
    IRQ = 10
    DOORBELL = 0x58c00004
    # Command registers (halfword: command id, 0 = buffer free; payload words follow at +2). The ARM marks a
    # register 0xfffe while the DSP image is not booted; the booted DSP image frees it.
    COMMANDS = (0x5820005e, 0x58206e22)
    NOT_BOOTED = 0xfffe
    FRAME_CHUNKS = 40  # fast-mode chunks per 20 ms frame
    # Module-ready halfwords polled by the ARM (0x126adb6 returns the signed value; -1 means the DSP
    # module is up). Which one is read depends on the loaded image.
    DRIVER_STATE = 0x19ae45c
    READY_WORDS = (0x580008ce, 0x58007b84)

    def __init__(self, uc, interrupts):
        self.uc = uc
        self.interrupts = interrupts
        self.armed = False
        self.ticks = 0
        self.raised = 0
        self.ready_replies = 0
        self.sbi = SbiBus(uc)
        self.commands = []
        self.listeners = []  # called as listener(command, payload) for every command the DSP accepts
        for register in self.COMMANDS:
            uc.hook_add(UC_HOOK_MEM_READ, self.boot, begin=register, end=register + 1)
        uc.hook_add(UC_HOOK_MEM_WRITE, self.doorbell, begin=self.DOORBELL, end=self.DOORBELL + 3)
        for word in self.READY_WORDS:
            uc.hook_add(UC_HOOK_MEM_READ, self.ready, begin=word, end=word + 1)
        uc.hook_add(UC_HOOK_MEM_WRITE, self.descriptor, begin=self.DESCRIPTOR, end=self.DESCRIPTOR + 3)

    def descriptor(self, uc, access, address, size, value, _):
        self.armed = True

    def ready(self, uc, access, address, size, value, _):
        if size == 2:
            # The module driver (state byte at 0x19ae45c) first waits for -1 (image booted, states 1..4)
            # and later for 1 (module initialised, state 5).
            state = uc.mem_read(self.DRIVER_STATE, 1)[0]
            uc.mem_write(address, b'\xff\xff' if state < 5 else b'\x01\x00')
            self.ready_replies += 1

    def boot(self, uc, access, address, size, value, _):
        if int.from_bytes(uc.mem_read(address, 2), 'little') == self.NOT_BOOTED:
            uc.mem_write(address, b'\x00\x00')

    def doorbell(self, uc, access, address, size, value, _):
        # The DSP firmware would read the command, execute it and free the command register.
        for register in self.COMMANDS:
            command = int.from_bytes(uc.mem_read(register, 2), 'little')
            if command and command != self.NOT_BOOTED and command < 0x1000:
                payload = [int.from_bytes(uc.mem_read(register + 2 + 2 * i, 2), 'little') for i in range(8)]
                self.commands.append((command, register, payload))
                for listener in self.listeners:
                    listener(command, payload)
                uc.mem_write(register, b'\x00\x00')
                self.armed = True

    def advance(self):
        if not self.armed:
            return
        self.ticks += 1
        if self.ticks % self.FRAME_CHUNKS == 0:
            self.interrupts.raise_source(self.IRQ)
            self.raised += 1

    def report(self):
        return {'armed': self.armed, 'irq_raised': self.raised, 'ready_replies': self.ready_replies, 'sbi_transfers': self.sbi.transfers,
                'commands': [(hex(c), hex(r), [hex(w) for w in p]) for c, r, p in self.commands[:40]]}
