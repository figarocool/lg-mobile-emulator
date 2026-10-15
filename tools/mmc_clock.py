"""MMC clock start/stop subset, inferred from firmware mmc_stop_clock()."""
from unicorn import UC_HOOK_MEM_WRITE, UcError

class MmcClock:
    BASE = 0x61800000

    def __init__(self):
        self.stopped = False
        self.starts = 0
        self.stops = 0
        self.map_page = None  # set by the emulator: maps the shadow page when the first access arrives

    def attach(self, uc):
        self.uc = uc
        # Mapping is supplied by the explicit shadow-MMIO option. Only writes are hooked: the firmware polls
        # the status register millions of times while it waits for a card that is not there, and a Python
        # callback per read made the boot minutes slower. The status bit is updated when the clock command
        # is written, so polling runs at native speed.
        uc.hook_add(UC_HOOK_MEM_WRITE, self.access, begin=self.BASE, end=self.BASE+3)

    def access(self, uc, access, address, size, value, _):
        if address != self.BASE or value not in (1, 2):
            return
        try:
            status = int.from_bytes(uc.mem_read(self.BASE+4, 4), 'little')
        except UcError:
            if self.map_page is None:
                raise
            self.map_page(self.BASE)  # first access: the shadow page does not exist yet
            status = 0
        if value == 1:
            self.stopped = True
            self.stops += 1
            status |= 0x100
        else:
            self.stopped = False
            self.starts += 1
            status &= ~0x100
        uc.mem_write(self.BASE+4, status.to_bytes(4, 'little'))

    def report(self):
        return {'clock_stopped': self.stopped, 'starts': self.starts, 'stops': self.stops,
                'limitations': ['clock state only', 'no SD card, commands, data or MMC interrupts']}
