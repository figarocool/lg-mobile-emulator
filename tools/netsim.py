"""Simulated radio network below the NAS: a stand-in for the RRC task.

The phone's real NAS (MM, REG, CM, SD, UI) runs unchanged. Everything under it, the access stratum (RRC, L1 and
the modem DSP), is replaced by this model: MM's commands to RRC are taken off the RRC queue (0x183e0c8) and
answered with the messages the real RRC would send, built with the firmware's own MM-buffer allocator
(0x12e0748) and sender (0x12de574).

Message layouts are recovered from the receiving code in mmcoord.c, see analysis/BOOT_PROGRESS.md.
"""
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1

from guest_call import call

Q_PUT = 0x1279116
MSG_SENDERS = (0x7c0654, 0xb8f47c, 0xeee1fc, 0x12dd490, 0x12dd484, 0xeee210, 0x7c07dc)
RRC_QUEUE = 0x183e0c8
ALLOC_MM = 0x12e0748       # ARM veneer: allocate an MM command buffer for a message id
SEND_MM = 0x12de574        # ARM veneer: queue the buffer to MM

RRC_SERVICE_REQ = 0x05000001
RRC_NAMES = {0x05000001: 'RRC_SERVICE_REQ', 0x0500000d: 'RRC_?_0d'}

MSG_SERVICE_CNF = 0x67
CM_OPRT_MODE = 0xd1a449    # cm_ph_cmd_oprt_mode(cb, data, client, mode); Thumb
OPRT_ONLINE = 5


def plmn_bytes(mcc, mnc):
    """RRC plmn_id: mcc[3], number of MNC digits, mnc[3]."""
    mnc_digits = [int(c) for c in mnc] + [0xf] * (3 - len(mnc))
    return bytes([int(c) for c in mcc] + [len(mnc)] + mnc_digits)


class Network:
    def __init__(self, uc, mcc='222', mnc='99', lac=1, cell_id=0x1001):
        self.uc = uc
        self.mcc, self.mnc, self.lac, self.cell_id = mcc, mnc, lac, cell_id
        self.pending = []          # MM -> RRC commands waiting to be answered
        self.online_request = False
        self.online_delay = 0
        self.went_online = False
        self.recent = []           # last MM debug lines (to name the commands seen)
        self.log = []
        self.sent = []
        uc.hook_add(UC_HOOK_CODE, self.queue_put, begin=Q_PUT, end=Q_PUT)
        for sender in MSG_SENDERS:
            uc.hook_add(UC_HOOK_CODE, self.message, begin=sender, end=sender)

    def message(self, uc, address, size, _):
        # The phone goes online by itself on a real handset (PhoneMngr); here that step is taken when the
        # SIM has finished initialising.
        try:
            fmt = int.from_bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R0) + 8, 4), 'little')
            text = bytes(uc.mem_read(fmt, 48)).split(b'\0')[0]
        except Exception:
            return
        if text.startswith((b'MM sent', b'MM State', b'Recd:', b'MM received', b'MM recved', b'Revd', b'Sending')):
            self.recent.append(text.decode('latin1'))
            del self.recent[:-6]
        if text.startswith(b'=CM= cm_ph_cmd_subscription_available') and not self.went_online:
            # the phone only registers once CM knows the subscription; ONLINE comes a little later
            self.went_online = True
            self.online_delay = 600

    # -- interception ------------------------------------------------------------------------------------------
    def queue_put(self, uc, address, size, _):
        if uc.reg_read(UC_ARM_REG_R0) != RRC_QUEUE:
            return
        item = uc.reg_read(UC_ARM_REG_R1)
        raw = bytes(uc.mem_read(item, 0x80))
        command = struct.unpack_from('<I', raw, 4)[0]
        self.pending.append((command, raw))
        self.log.append(('MM->RRC', hex(command), RRC_NAMES.get(command, '?'), list(self.recent[-2:]), raw[:48].hex()))
        # The command never reaches the real RRC: continue as if q_put had returned.
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    # -- replies -----------------------------------------------------------------------------------------------
    def safe_point(self):
        """Guest calls are only made when the interrupted code is an ordinary task (supervisor mode, IRQs open)."""
        cpsr = self.uc.reg_read(UC_ARM_REG_CPSR)
        return cpsr & 0x1f == 0x13 and not cpsr & 0x80

    def go_online(self):
        self.online_request = True

    def busy(self):
        if self.online_delay:
            self.online_delay -= 1
            if not self.online_delay:
                self.online_request = True
        return bool(self.pending) or self.online_request

    def service(self):
        if not self.busy() or not self.safe_point():
            return
        if self.online_request:
            self.online_request = False
            call(self.uc, CM_OPRT_MODE, (0, 0, 0xffffffff, OPRT_ONLINE), thumb=True)
            self.log.append(('CM', 'oprt_mode ONLINE'))
            return
        command, raw = self.pending.pop(0)
        if command == RRC_SERVICE_REQ:
            self.send_service_cnf(raw)

    def new_mm_message(self, message_id):
        buffer = call(self.uc, ALLOC_MM, (message_id,), thumb=False)
        if not buffer:
            raise RuntimeError('MM buffer pool exhausted')
        return buffer

    def send_service_cnf(self, request):
        uc = self.uc
        buffer = self.new_mm_message(MSG_SERVICE_CNF)
        uc.mem_write(buffer + 8, bytes([1]))                              # status: service available
        uc.mem_write(buffer + 0xd, plmn_bytes(self.mcc, self.mnc))
        uc.mem_write(buffer + 0x14, bytes([1]))                           # LAC present
        uc.mem_write(buffer + 0x1c, self.lac.to_bytes(2, 'big'))
        uc.mem_write(buffer + 0x24, (1).to_bytes(4, 'little'))            # one CN domain entry follows
        uc.mem_write(buffer + 0x28, bytes([1]))                           # entry valid
        call(uc, SEND_MM, (buffer,), thumb=False)
        self.sent.append(('RRC->MM', 'RRC_SERVICE_CNF'))

    def report(self):
        return {'log': self.log[-40:], 'sent': self.sent[-40:]}
