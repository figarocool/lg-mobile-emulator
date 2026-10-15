"""Phone identity (IMEI, Bluetooth address) served to the firmware through its own NV command queue.

Every NV access of the firmware goes through the command queue entry 0x10d219a (cmd struct: +4 item,
+6 write flag, +8 data pointer, +0xc requester TCB, +0x10 signal mask, +0x18 status). For a read of an
overridden item the model fills the caller's buffer, sets status 0 (NV_DONE) and raises the requester's
signal itself (rex_set_sigs, 0x1265dec) instead of letting the NV task look in flash, so the original
callers cannot tell the difference. Writes are left alone.
"""
import re

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1

NV_QUEUE = 0x10d219a
REX_SET_SIGS = 0x1265dec
NV_UE_IMEI = 550
NV_BD_ADDR = 447
ZERO_RECORD = bytes(128)  # NV records are at most 128 bytes


def luhn_digit(digits14):
    total = 0
    for index, char in enumerate(reversed(digits14)):
        value = int(char) * (2 if index % 2 == 0 else 1)
        total += value - 9 if value > 9 else value
    return str((10 - total % 10) % 10)


def normalize_imei(text):
    """15 digits with a valid Luhn check digit. 14 digits get the check digit appended."""
    digits = re.sub(r'[\s-]', '', text)
    if not digits.isdigit() or len(digits) not in (14, 15):
        raise ValueError('IMEI: servono 14 o 15 cifre')
    if len(digits) == 14:
        return digits + luhn_digit(digits)
    if luhn_digit(digits[:14]) != digits[14]:
        raise ValueError('IMEI: cifra di controllo errata (dovrebbe essere %s)' % luhn_digit(digits[:14]))
    return digits


def imei_nv(imei):
    """NV_UE_IMEI_I layout: length 8, then the mobile identity: (digit1 << 4) | 0xa, then digit pairs, low digit first."""
    digits = [int(c) for c in normalize_imei(imei)]
    body = [(digits[0] << 4) | 0xa] + [(digits[i + 1] << 4) | digits[i] for i in range(1, 15, 2)]
    return bytes([8] + body)


def parse_bd_addr(text):
    pairs = re.findall(r'[0-9A-Fa-f]{2}', text.replace(':', ' ').replace('-', ' '))
    if len(pairs) != 6 or len(re.sub(r'[\s:-]', '', text)) != 12:
        raise ValueError('Indirizzo Bluetooth: servono 6 byte esadecimali (AA:BB:CC:DD:EE:FF)')
    return bytes(int(p, 16) for p in pairs)


def bd_addr_nv(text):
    """bt_bd_addr_type keeps the least significant byte first."""
    return parse_bd_addr(text)[::-1]


class NvOverride:
    def __init__(self, uc, items, zero_items=()):
        self.uc = uc
        self.items = dict(items)
        for item in zero_items:
            self.items.setdefault(item, ZERO_RECORD)
        self.served = {}
        self.missed = []
        uc.hook_add(UC_HOOK_CODE, self.queue, begin=NV_QUEUE, end=NV_QUEUE)

    def queue(self, uc, address, size, _):
        cmd = uc.reg_read(UC_ARM_REG_R0)
        item = int.from_bytes(uc.mem_read(cmd + 4, 2), 'little')
        if item not in self.items or int.from_bytes(uc.mem_read(cmd + 6, 2), 'little') != 0:
            return
        data = self.items[item]
        pointer = int.from_bytes(uc.mem_read(cmd + 8, 4), 'little')
        uc.mem_write(pointer, data)
        uc.mem_write(cmd + 0x18, b'\x00\x00')
        tcb = int.from_bytes(uc.mem_read(cmd + 0xc, 4), 'little')
        signals = int.from_bytes(uc.mem_read(cmd + 0x10, 4), 'little')
        self.served[item] = self.served.get(item, 0) + 1
        # Continue as rex_set_sigs(tcb, signals) returning straight to the NV caller.
        uc.reg_write(UC_ARM_REG_R0, tcb)
        uc.reg_write(UC_ARM_REG_R1, signals)
        uc.reg_write(UC_ARM_REG_PC, REX_SET_SIGS | 1)

    def report(self):
        return {'items_served': {str(k): v for k, v in self.served.items()}}
