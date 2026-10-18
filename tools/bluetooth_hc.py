"""Bluetooth controller model: the boot handshake the ARM driver needs from the baseband.

Reversed from btdc.c/btqdspq.c (service bt) and the RM/HC stack (bthc.c, bthcev.c, bthclc.c):
Bluetooth on the MSM6250 is not an external chip on a UART; the baseband runs as a QDSP image,
and the ARM driver manages it through the same acquire/release mailbox as WCDMA/GSM
(mdsp_management.py's module table at 0x19a39dc, functions at 0x10abc46/0x10abcb6 -- "MDSP_REQ"/
"MDSP_REL" in this file's terms). Unlike the camera (image 0x15) or audio (image 0xc/1), bringing
up Bluetooth does *not* exchange any messages with the DSP's own memory (0x58xxxxxx): the request
is satisfied synchronously in ARM code (the camera/audio images are genuinely absent here), and the
driver only waits for a single ready halfword plus the module's completion interrupt:
  - 0x50007e0e (a halfword in the WCDMA/BT shared RAM state table, read at 0x10f2dec/0x10f2df4) must
    read a non-zero value once the "driver" (0x1dda0e4, byte 0 = state, states 0..5+; it reaches at
    least 2 once the image mailbox round-trips) is ready to receive the module interrupt;
  - interrupt source 9 (the next IRQ above MdspManagement's own source 5) must then fire once, which
    drives the ARM-side state machine from "enabling" to "powered" (0x1985e0, confirmed to then
    auto-enable AG/OPP/GOEP/AVRCP/SPP without further input).
Once this handshake is delivered, `bluetooth_isPowerOn()` becomes TRUE and the phone's own Bluetooth
menu (power on/off, device list, "Periferiche associate") works entirely in ARM code; no further
model is needed for that part.

Device discovery (bt_pdk_startDiscovery -> "HC CMD RX: HC Inq") is NOT modelled here: tracing it
shows the inquiry handler calling into the same slot-scheduling helpers GSM/WCDMA L1 use for timing
(0x1228390, 0x15d9548, 0x163dxxx), i.e. it expects a real radio search to run over several seconds of
emulated time and complete via a DSP-side event this reversing pass did not fully recover. Left
undone; see analysis/BOOT_PROGRESS.md.
"""
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE

READY_WORD = 0x50007e0e
DRIVER_STATE = 0x1dda0e4
MDSP_APP_TABLE = 0x19a39dc        # 8 entries x 0x28 bytes; +1 = state, +4 = acquired module mask
BT_SLOT = 4                       # firmware slot bt_dc acquires (module mask 2)
POLL_SITE = 0xd51680              # bt_pdk's own idle poll (any frequently-hit BT code address works)
IRQ_SOURCE = 9


class BluetoothController:
    """Delivers the BT module's boot-ready handshake once the driver is waiting for it."""

    def __init__(self, uc, interrupts):
        self.uc = uc
        self.interrupts = interrupts
        self.done = False
        self.power_requests = 0
        uc.hook_add(UC_HOOK_CODE, self.poll, begin=POLL_SITE, end=POLL_SITE)

    def ready(self):
        driver_state = self.uc.mem_read(DRIVER_STATE, 1)[0]
        app_state = self.uc.mem_read(MDSP_APP_TABLE + 0x28 * BT_SLOT + 1, 1)[0]
        return driver_state == 2 and app_state == 3

    def poll(self, uc, address, size, _):
        driver_state = uc.mem_read(DRIVER_STATE, 1)[0]
        if driver_state < 2:
            self.done = False   # powered off (or not yet up): re-arm for the next power-on
        if self.done or not self.ready():
            return
        uc.mem_write(READY_WORD, (1).to_bytes(2, 'little'))
        self.interrupts.raise_source(IRQ_SOURCE)
        self.done = True
        self.power_requests += 1

    def report(self):
        return {'handshake_delivered': self.done}
