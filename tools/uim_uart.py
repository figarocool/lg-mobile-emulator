"""Inferred UIM UART at 0x84000c80 with a minimal USIM, for the original uimdrv.c driver.

Register roles are inferred from the firmware, not documented:
  +0x0c  status (read): bit0 = a received byte is available (polled at 0xb6b410)
  +0x18  command (write): 0x01 observed right before waiting for the ATR
Everything else is stored and logged until its meaning is established.
The card is a model, not a dump of a real SIM.
"""
from collections import deque
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_READ
from unicorn.arm_const import UC_ARM_REG_PC
from usim_card import UsimCard

BASE = 0x84000c80
SIZE = 0x80
STATUS = BASE + 0x0c
TRANSMIT = BASE + 0x10  # transmit FIFO: 0xff written first by uim_send_pps (0xb68c34)
RECEIVE = BASE + 0x14  # data register read by the ISR state handlers (0xb6a7ea)
ISR = BASE + 0x24  # masked interrupt status read by the ISR at 0xb6aadc
IMR = BASE + 0x1c
ATR_POLL_PC = 0xb6b410
IRQ_SOURCE = 28  # vector of the UART entry (0xb6aee3) in the ISR table at 0x1764b10
COMMAND = BASE + 0x18


def tck(data):
    value = 0
    for byte in data:
        value ^= byte
    return value


# Realistic 3G USIM ATR: direct convention; TA1=0x96 (Fi=512, Di=32); T=0 and T=15 (TA3=0xC7: clock
# stop allowed, classes A/B/C); 15 historical bytes; TCK is the XOR of T0..last historical byte.
_BODY = bytes([0x9f, 0x96, 0x80, 0x1f, 0xc7, 0x80, 0x31, 0xe0, 0x73, 0xfe, 0x21, 0x1b, 0x64, 0x07, 0x4c, 0x54,
               0x80, 0x82, 0x90, 0x00])
FULL_ATR = bytes([0x3b]) + _BODY
DEFAULT_ATR = FULL_ATR + bytes([tck(_BODY)])  # T=15 is declared, so the ISR expects the TCK byte


class UimUart:
    def __init__(self, uc, timer=None, atr=DEFAULT_ATR):
        self.uc = uc
        self.timer = timer
        self.irq_raised = 0
        self.atr = bytes(atr)
        self.rx = deque()
        self.rx_enabled = False
        self.delivered = False
        self.rx_bytes_read = 0
        import os
        sim = os.environ.get('U310_SIM')
        profile = state = None
        if sim:
            import sim_profile
            profile = sim_profile.load(sim)
            state = sim_profile.state_path(sim)
        pin_env = os.environ.get('U310_PIN')
        pin_prompt = (pin_env != 'off') if pin_env else bool((profile or {}).get('pin_enabled', True))
        self.card = UsimCard(pin_prompt=pin_prompt, profile=profile, state_path=state)
        self.tx = bytearray()
        self.log = deque(maxlen=4000)
        self.reads = 0
        uc.hook_add(UC_HOOK_MEM_READ, self.access, begin=BASE, end=BASE + SIZE - 1)
        uc.hook_add(UC_HOOK_MEM_WRITE, self.access, begin=BASE, end=BASE + SIZE - 1)

    def note(self, op, address, value):
        entry = [op, hex(address), hex(value), hex(self.uc.reg_read(UC_ARM_REG_PC)), 1]
        if self.log and self.log[-1][:4] == entry[:4]:
            self.log[-1][4] += 1
        else:
            self.log.append(entry)

    def status_word(self):
        return 0x01 if self.rx else 0x0

    def access(self, uc, access, address, size, value, _):
        if access == UC_MEM_READ:
            if address == STATUS:
                if (self.rx_enabled and not self.delivered
                        and uc.reg_read(UC_ARM_REG_PC) == ATR_POLL_PC):
                    # The driver is waiting for the first ATR byte (poll at 0xb6b410).
                    self.delivered = True
                    self.card.reset()
                    self.rx.clear()
                    self.rx.extend(self.atr)
                    self.raise_irq()
                word = self.status_word() | 0x0c  # TXRDY and TXEMT always set
                uc.mem_write(address, word.to_bytes(4, 'little'))
            elif address == RECEIVE:
                byte = self.rx.popleft() if self.rx else 0
                uc.mem_write(address, byte.to_bytes(4, 'little'))
                self.rx_bytes_read += 1
                # No new IRQ here: the ISR (0xb6aadc) loops itself while the status shows data, and
                # re-raising would nest the non-reentrant handler and store the ATR in reverse.
            elif address == ISR:
                imr = int.from_bytes(uc.mem_read(IMR, 4), 'little')
                uc.mem_write(address, (imr & (0x10 if self.rx else 0)).to_bytes(4, 'little'))  # RXLEV
            self.reads += 1
            self.note('r', address, int.from_bytes(uc.mem_read(address, 4), 'little'))
            return
        self.note('w', address, value)
        if address == TRANSMIT:
            byte = value & 0xff
            self.tx.append(byte)
            # Single-wire I/O line: every transmitted byte is echoed into the receiver, and the driver
            # drains it in the TX state handler (0xb68c7e).
            self.rx.append(byte)
            reply = self.card.receive(byte)
            if reply:
                self.rx.extend(reply)
            self.raise_irq()
            return
        if address == COMMAND:
            if value == 0x01:
                self.rx_enabled = True
                self.delivered = False  # every card reset is answered with a new ATR
            elif value == 0x10:  # reset receiver: flush the FIFO
                self.rx.clear()

    def raise_irq(self):
        if self.timer is not None and self.rx:
            self.timer.raise_source(IRQ_SOURCE)
            self.irq_raised += 1

    def snapshot(self):
        """State saved in checkpoints so a resumed run keeps talking to the same card."""
        return {'rx': list(self.rx), 'rx_enabled': self.rx_enabled, 'delivered': self.delivered,
                'card': self.card.snapshot()}

    def load(self, snap):
        self.rx = deque(snap['rx'])
        self.rx_enabled, self.delivered = snap['rx_enabled'], snap['delivered']
        self.card.load(snap['card'])

    def report(self):
        mask = int.from_bytes(self.uc.mem_read(0x84000250, 4), 'little')
        return {'irq_mask_0x84000250': hex(mask), 'kind': 'inferred UIM UART + minimal USIM model', 'atr': self.atr.hex(),
                'rx_pending': len(self.rx), 'tx': bytes(self.tx[-64:]).hex(), 'apdu_count': len(self.card.apdus), 'apdus': self.card.apdus[:70], 'apdus_tail': self.card.apdus[-6:], 'pps': [p.hex() for p in self.card.pps], 'rx_bytes_read': self.rx_bytes_read, 'irq_raised': self.irq_raised, 'rx_enabled': self.rx_enabled, 'log': list(self.log),
                'verified': False}
