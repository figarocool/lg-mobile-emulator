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
CM_RPT_DISPATCH = 0xeb6bdc       # cmss report dispatcher (Thumb): r0 = report whose +8 points to the message
SIGNAL_SCRATCH = 0x04f02000
CM_TCB = 0x1be9eb8
CM_REPORT_QUEUE = 0x19c0f4c      # drained by cmtask.c when signal 2 is set
CM_REPORT_SIGNAL = 2
CM_ALLOC_ITEM = 0x126ff2e         # allocate a 0x5c4-byte CM item from the pool
REX_SET_SIGS = 0x1265dec
RRC_MEASUREMENT = 0x1e772b0
CM_SS = 0x19bcc68
CM_SIGNAL_STORE = 0x19bd6c8       # cmss signal record: +0xa/+0xc current, +0x1a/+0x1c reported (rssi in -dBm, 125 = none)
RRC_NAMES = {0x05000001: 'RRC_SERVICE_REQ', 0x0500000d: 'RRC_?_0d'}

MSG_SERVICE_CNF = 0x67
CM_OPRT_MODE = 0xd1a449    # cm_ph_cmd_oprt_mode(cb, data, client, mode); Thumb
OPRT_ONLINE = 5


def plmn_bytes(mcc, mnc):
    """RRC plmn_id: mcc[3], number of MNC digits, mnc[3]."""
    mnc_digits = [int(c) for c in mnc] + [0xf] * (3 - len(mnc))
    return bytes([int(c) for c in mcc] + [len(mnc)] + mnc_digits)


class Network:
    def __init__(self, uc, mcc='222', mnc='99', lac=1, cell_id=0x1001, rssi=65, signal_file=None):
        self.uc = uc
        self.signal_file = signal_file
        self.signal_polls = 0
        self.mcc, self.mnc, self.lac, self.cell_id = mcc, mnc, lac, cell_id
        self.pending = []          # MM -> RRC commands waiting to be answered
        self.online_request = False
        self.online_delay = 0
        self.went_online = False
        self.recent = []           # last MM debug lines (to name the commands seen)
        self.log = []
        self.sent = []
        self.cnf_options = {}
        self.rssi = int(rssi)      # signal strength reported to CM after camping, in -dBm (125 = no signal)
        self.signal_wait = 400    # service() polls between camping and the first signal report
        self.signal_delay = 0
        self.handlers = {}        # MM->RRC command -> function(raw) answering it
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

    def inject(self, message_id, fill=None, on_sent=None):
        """Queue an arbitrary RRC->MM message (fill(buffer) writes the payload)."""
        self.injections = getattr(self, 'injections', [])
        self.injections.append((message_id, fill, on_sent))

    def poll_signal_file(self):
        """The window writes the wanted signal strength (-dBm) to a file; a change is reported to CM."""
        self.signal_polls += 1
        if not self.signal_file or self.signal_polls % 200 or self.signal_delay:
            return
        try:
            value = int(open(self.signal_file).read().strip())
        except (OSError, ValueError):
            return
        if value != self.rssi and 30 <= value <= 125:
            self.rssi = value
            self.report_signal(value)

    def busy(self):
        self.poll_signal_file()
        if self.signal_delay:
            self.signal_delay -= 1
            if not self.signal_delay:
                self.report_signal(self.rssi)
        if getattr(self, 'signal_requests', None) or getattr(self, 'injections', None):
            return True
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
        if getattr(self, 'signal_requests', None):
            self.send_signal(*self.signal_requests.pop(0))
            return
        if getattr(self, 'injections', None):
            message_id, fill, on_sent = self.injections.pop(0)
            buffer = self.new_mm_message(message_id)
            if fill:
                fill(self.uc, buffer)
            if on_sent:
                on_sent(message_id)
            call(self.uc, SEND_MM, (buffer,), thumb=False)
            self.sent.append(('RRC->MM', hex(message_id)))
            return
        if not self.pending:
            return
        command, raw = self.pending.pop(0)
        if command == RRC_SERVICE_REQ:
            self.send_service_cnf(raw)
        elif command in self.handlers:
            self.handlers[command](raw)

    def report_signal(self, rssi, command=0x29, ber=0):
        """Queue a signal-strength report for CM (rssi as a positive number of -dBm, 125 = no signal)."""
        self.signal_requests = getattr(self, 'signal_requests', [])
        self.signal_requests.append((rssi, command, ber))

    def send_signal(self, rssi, command, ber):
        """Deliver a signal report to the CM task the way an RR/L1 task would: fill the RRC measurement store the
        report handler reads (0x1e772b0+0x16), then queue a report item on the CM report queue and signal the task."""
        uc = self.uc
        # The UI derives the bars from both the RSSI and the Ec/Io it finds in the RRC measurement store
        # (value / 2 in dB, table thresholds 13/13/15/18); a plausible Ec/Io is derived from the RSSI.
        ecio = max(1, min(24, round((int(rssi) - 50) / 3)))
        for offset in (0x16, 0x1a):
            uc.mem_write(RRC_MEASUREMENT + offset, (2 * ecio).to_bytes(2, 'little'))
        uc.mem_write(CM_SS + 2, int(rssi).to_bytes(2, 'little'))
        uc.mem_write(CM_SIGNAL_STORE + 0x1a, int(rssi).to_bytes(2, 'little'))
        item = call(uc, CM_ALLOC_ITEM, (), thumb=True)
        if not item:
            raise RuntimeError('CM item pool exhausted')
        uc.mem_write(item + 4, command.to_bytes(2, 'little'))
        uc.mem_write(item + 0x18, bytes([rssi & 0xff, ber & 0xff]))   # rssi (-dBm), second byte copied to CM_SS+1
        call(uc, Q_PUT | 1, (CM_REPORT_QUEUE, item), thumb=True)
        call(uc, REX_SET_SIGS | 1, (CM_TCB, CM_REPORT_SIGNAL), thumb=True)
        self.sent.append(('CM', f'signal report cmd={command:#x} value={rssi}'))

    def new_mm_message(self, message_id):
        buffer = call(self.uc, ALLOC_MM, (message_id,), thumb=False)
        if not buffer:
            raise RuntimeError('MM buffer pool exhausted')
        return buffer

    def send_service_cnf(self, request):
        uc = self.uc
        options = self.cnf_options
        buffer = self.new_mm_message(MSG_SERVICE_CNF)
        uc.mem_write(buffer + 8, bytes([options.get('status', 1)]))       # status: service available
        uc.mem_write(buffer + 0xd, plmn_bytes(self.mcc, self.mnc))
        uc.mem_write(buffer + 0x14, bytes([1]))                           # LAC present
        uc.mem_write(buffer + 0x1c, self.lac.to_bytes(2, 'big'))
        # CN domain system information, 16 bytes per entry: +0 domain (0 = CS, 1 = PS), +4 length, +8 data.
        # CS data: T3212 (0 = no periodic update), flags (bit 0: IMSI attach required; 0 = the SIM's location info is current).
        # PS data: routing area code, flags (bit 0: network mode of operation I).
        entries = options.get('entries', ((0, bytes([0, 0])), (1, bytes([1, 1]))))
        uc.mem_write(buffer + 0x24, len(entries).to_bytes(4, 'little'))
        for index, (domain, data) in enumerate(entries):
            base = buffer + 0x28 + 16 * index
            uc.mem_write(base, bytes([domain, 0, 0, 0]) + len(data).to_bytes(4, 'little') + bytes(data))
        for offset, value in options.get('poke', {}).items():
            uc.mem_write(buffer + offset, bytes(value))
        call(uc, SEND_MM, (buffer,), thumb=False)
        self.sent.append(('RRC->MM', 'RRC_SERVICE_CNF'))
        self.signal_delay = self.signal_wait

    def report(self):
        return {'log': self.log[-40:], 'sent': self.sent[-40:]}
