"""Observed register storage at 0x58c/0x50c; function of the banks is unknown."""
from collections import Counter
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_READ
from unicorn import UC_PROT_READ, UC_PROT_WRITE

class RegisterBanks:
    # USB-related pages are referenced by usbdc.c and the IRQ 0x1d setup.
    # These remain register storage, without USB transfer/interrupt semantics.
    BASES = (0x58c00000, 0x50c00000, 0x65800000, 0x65000000)

    def __init__(self):
        self.accesses = Counter()
        self.dsp_writes = 0
        self.dsp_write_min = None
        self.dsp_write_max = None

    def attach(self, uc):
        for base in self.BASES:
            uc.mem_map(base, 0x1000)
            uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self.access,
                        begin=base, end=base+0xfff)
        # QDSP task copies 16-bit microcode here; this is storage, not DSP execution.
        for base in (0x58000000, 0x58200000, 0x58400000, 0x58800000,
                     0x50000000, 0x50200000, 0x50400000, 0x50800000):
            uc.mem_map(base, 0x40000, UC_PROT_READ | UC_PROT_WRITE)
            uc.hook_add(UC_HOOK_MEM_WRITE, self.dsp_access, begin=base, end=base+0x3ffff)

    def dsp_access(self, uc, access, address, size, value, _):
        self.dsp_writes += 1
        self.dsp_write_min = address if self.dsp_write_min is None else min(self.dsp_write_min, address)
        self.dsp_write_max = address+size-1 if self.dsp_write_max is None else max(self.dsp_write_max, address+size-1)

    def access(self, uc, access, address, size, value, _):
        self.accesses[(address, 'read' if access == UC_MEM_READ else 'write')] += 1

    def report(self):
        return {'semantics': 'diagnostic register storage only; controller function unknown',
                'dsp_memory': {'windows': [f'0x{b:08x}-0x{b+0x3ffff:08x}' for b in
                    (0x58000000,0x58200000,0x58400000,0x58800000,0x50000000,0x50200000,0x50400000,0x50800000)], 'writes': self.dsp_writes,
                               'min': self.dsp_write_min, 'max': self.dsp_write_max,
                               'executes_dsp_code': False},
                'accesses': [{'address': hex(a), 'operation': op, 'count': n}
                             for (a, op), n in self.accesses.most_common()]}
