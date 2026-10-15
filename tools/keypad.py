"""5-row/7-column scan subset inferred from original 0x1444042.

Rows are active low at GPIO 0x48000070. Seven column drive patterns
are stored at 0x14b9b78. Key labels, debounce and interrupts are unknown.
"""
from unicorn import UC_HOOK_MEM_READ, UcError


class Keypad:
    INPUT = 0x48000070
    OUTPUT_A = 0x48000000
    OUTPUT_B = 0x84000150
    SENSE = 0x84000170  # bit 9 is the power key line, active low (0x1443928 prints power_key_pressed when clear)
    SENSE_BIT = 1 << 9
    COLUMN_A = (0x4000, 0x2000, 0x1000, 0x800, 0x400, 0x40, 0)
    COLUMN_B = (0, 0, 0, 0, 0, 0, 0x40000)

    MIN_HOLD_SECONDS = 0.08  # a tap must last longer than the firmware's scan + debounce, in emulated time

    def __init__(self, uc, keys_file=None, clock=None):
        self.uc = uc
        self.clock = clock  # callable returning emulated seconds; None disables the minimum hold
        self.held_since = {}
        self.file_held = set()
        self.keys_file = keys_file
        self.keys_mtime = None
        self.pressed = set()
        self.power_pressed = False
        self.reads = 0
        uc.hook_add(UC_HOOK_MEM_READ, self.read, begin=self.INPUT, end=self.INPUT+3)
        uc.hook_add(UC_HOOK_MEM_READ, self.read_sense, begin=self.SENSE, end=self.SENSE+3)

    def set_key(self, row, column, down):
        if not 0 <= row < 5 or not 0 <= column < 7:
            raise ValueError('Key coordinates require row 0..4 and column 0..6')
        if down:
            self.pressed.add((row, column))
        else:
            self.pressed.discard((row, column))

    def poll_keys_file(self):
        """Live input: the file holds space separated ROW,COL pairs held down, and P for the power key."""
        if not self.keys_file:
            return
        try:
            mtime = self.keys_file.stat().st_mtime_ns
            if mtime != self.keys_mtime:
                self.keys_mtime = mtime
                items = self.keys_file.read_text().split()
                self.power_pressed = 'P' in items
                self.file_held = {tuple(int(v) for v in item.split(',')) for item in items if item != 'P'}
        except (OSError, ValueError):
            pass
        now = self.clock() if self.clock else 0.0
        for key in self.file_held:
            self.held_since.setdefault(key, now)
        # A key released too soon stays down until the minimum hold has elapsed (emulated time).
        self.held_since = {key: since for key, since in self.held_since.items()
                           if key in self.file_held or now - since < self.MIN_HOLD_SECONDS}
        self.pressed = {key for key in self.held_since if 0 <= key[0] < 5 and 0 <= key[1] < 7}

    def read_sense(self, uc, access, address, size, value, _):
        self.poll_keys_file()
        try:
            word = int.from_bytes(uc.mem_read(self.SENSE, 4), 'little')
        except UcError:
            word = 0
        # Released = line high. Holding the power key pulls it low: a long hold makes the firmware power off.
        word = word & ~self.SENSE_BIT if self.power_pressed else word | self.SENSE_BIT
        uc.mem_write(self.SENSE, word.to_bytes(4, 'little'))

    def read(self, uc, access, address, size, value, _):
        self.poll_keys_file()
        if address != self.INPUT:
            return
        def output(address):
            try:
                return int.from_bytes(uc.mem_read(address, 4), 'little')
            except UcError:
                return 0  # Same reset storage value before the shadow page is mapped.
        drive_a = output(self.OUTPUT_A)
        drive_b = output(self.OUTPUT_B)
        rows = 0x1f
        for row, col in self.pressed:
            if drive_a & self.COLUMN_A[col] or drive_b & self.COLUMN_B[col]:
                rows &= ~(1 << row)
        original = int.from_bytes(uc.mem_read(address, 4), 'little')
        uc.mem_write(address, ((original & ~0x1f) | rows).to_bytes(4, 'little')[:size])
        self.reads += 1

    def report(self):
        return {'kind': 'inferred active-low 5x7 keypad scan', 'reads': self.reads,
                'pressed': sorted(self.pressed),
                'limitations': ['key labels unknown', 'no debounce or keypad IRQ',
                                'other GPIO inputs retain diagnostic storage']}
