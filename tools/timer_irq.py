"""Inferred IRQ0 sleep-clock timer, with approximate instruction-based time.

32.768 kHz count register and IRQ0 inferred from 0x156d34 and 0x156df4.
Low-bank peripheral IRQs can also be latched. Hardware priority arbitration
is not modeled. Vector relocation is an explicit hypothesis.
"""
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_READ, UcError
from unicorn.arm_const import UC_ARM_REG_CPSR, UC_ARM_REG_PC, UC_ARM_REG_SPSR, UC_ARM_REG_LR

def enter_irq(uc, vector_base):
    old = uc.reg_read(UC_ARM_REG_CPSR)
    if old & 0x80:
        return False
    pc = uc.reg_read(UC_ARM_REG_PC)
    uc.reg_write(UC_ARM_REG_CPSR, (old & ~0x3f) | 0x12 | 0x80)
    uc.reg_write(UC_ARM_REG_SPSR, old)
    uc.reg_write(UC_ARM_REG_LR, pc + 4)
    uc.reg_write(UC_ARM_REG_PC, vector_base + 0x18)
    return True

class TimerIRQ:
    PERIOD = 0x80003450
    STATUS = 0x84000240
    ACK = 0x84000248
    MASK = 0x84000250
    VECTORS = (0x840002b0, 0x840002c0)
    VECTOR_BASE = 0x0005c000  # Candidate firmware table, not confirmed reset-ROM relocation.
    CPU_HZ = 180000000
    CLOCK_HZ = 32768

    def __init__(self):
        self.cycles = 0
        self.deadline = 0
        self.period = 0
        self.pending = False
        self.raised = 0
        self.delivered = 0
        self.acks = 0
        self.fast_forwards = 0
        self.inflight = False
        self.peripheral_pending = 0
        self.delivered_sources = {}

    def raise_source(self, source):
        """Latch a low-bank peripheral IRQ. Source zero belongs to the timer."""
        if not 1 <= source < 32:
            raise ValueError('Peripheral IRQ must be in 1..31')
        self.peripheral_pending |= 1 << source

    def pending_bits(self):
        return int(self.pending) | self.peripheral_pending

    def enabled_bits(self):
        return self.pending_bits() & self.read32(self.MASK)

    def attach(self, uc):
        self.uc = uc
        uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self.memory,
                    begin=self.STATUS, end=0x840002c3)
        uc.hook_add(UC_HOOK_MEM_WRITE, self.memory, begin=self.PERIOD, end=self.PERIOD+3)

    def read32(self, address):
        try:
            return int.from_bytes(self.uc.mem_read(address, 4), 'little')
        except UcError:
            return 0

    def initialize_after_restore(self):
        self.period = self.read32(self.PERIOD) & 0xffff
        self.deadline = self.cycles + self.period_cycles()

    def period_cycles(self):
        return max(1, self.period * self.CPU_HZ // self.CLOCK_HZ)

    def memory(self, uc, access, address, size, value, _):
        if access == UC_MEM_READ:
            if address == self.STATUS:
                uc.mem_write(address, self.pending_bits().to_bytes(4, 'little')[:size])
            elif address in self.VECTORS:
                enabled = self.enabled_bits()
                vector = (enabled & -enabled).bit_length()-1 if enabled else 0x3f
                uc.mem_write(address, vector.to_bytes(4, 'little')[:size])
        elif address == self.ACK:
            if value & 1:
                self.pending = False
                self.acks += 1
            self.peripheral_pending &= ~value
            self.inflight = False
        elif address == self.PERIOD:
            self.period = value & 0xffff
            self.deadline = self.cycles + self.period_cycles()

    def advance(self, idle=False, instructions=1):
        self.cycles += instructions  # Approximation: one CPU cycle per instruction.
        if idle and self.period and self.read32(self.MASK) & 1:
            self.cycles = max(self.cycles, self.deadline)
            self.fast_forwards += 1
        if self.period and self.cycles >= self.deadline:
            if not self.pending:
                self.raised += 1
            self.pending = True
            self.deadline = self.cycles + self.period_cycles()
        # No IRQ can be delivered without a pending source. Avoid a Unicorn
        # memory/register round trip on every ordinary basic block.
        if self.inflight or not self.pending_bits():
            return False
        return bool(self.enabled_bits()) and not self.uc.reg_read(UC_ARM_REG_CPSR) & 0x80

    def report(self):
        return {'period_32khz_counts': self.period, 'cycles': self.cycles,
                'deadline': self.deadline, 'pending': self.pending,
                'raised': self.raised, 'delivered': self.delivered, 'acks': self.acks,
                'delivered_sources': self.delivered_sources,
                'fast_forwards': self.fast_forwards, 'inflight': self.inflight, 'mask': hex(self.read32(self.MASK)),
                'peripheral_pending': hex(self.peripheral_pending),
                'vector_base': hex(self.VECTOR_BASE),
                'limitations': ['one cycle per instruction approximation',
                                'low bank only; lowest source wins, hardware priorities unimplemented',
                                'vector relocation hypothesis', 'no FIQ']}
