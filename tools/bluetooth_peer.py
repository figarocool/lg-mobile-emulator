"""A synthetic Bluetooth peer: explicit, documented HLE for device discovery and pairing.

Reversing status (see analysis/BOOT_PROGRESS.md): `bt_pdk_startDiscovery` ("HC CMD RX: HC Inq")
drives a real radio-timed search through the same slot-scheduling helpers GSM/WCDMA L1 use
(0x1228390, 0x15d9548, the 0x163dxxx block); a run of more than 10 emulated seconds after starting
it never completes on its own, and the exact wire format of the internal "HC Inquiry Result /
Inquiry Complete" event (built by small helpers around 0x1296570/0x12965d6 and received by the
generic dispatcher at 0x12964a4, event code at +4 of the record) was not pinned down with
confidence in the time available.

Rather than guess at that format, this module skips the whole RM/HC inquiry protocol and writes
directly into the single structure both device-discovery UI screens and the paired-device list
ultimately read, reverse-engineered byte-exact from `bt_pdk_deviceEnumNext` / `bluetooth_getPairedDeviceInfo`
(0xe307e0, 0xe306dc) and `bluetooth_startDiscovery` (0xe2fdbe):

    0x202dcd0  u8   known-device count ("nPairedDevs")
    0x202dcd1  u8   (cleared by bluetooth_startDiscovery; purpose not identified)
    0x202dcd2  u8   (cleared by bluetooth_startDiscovery; purpose not identified)
    0x202dcf9  u8   BTSD.state: 0 = idle, 1..6 = an HC command is in flight (shared by every async
                    BT operation that goes through the submit function at 0xe7395c, not only
                    discovery; states 1..3 are "cancel back to idle" when re-entered)
    0x202dd01  +index*0xca   device table, one entry per known device:
        +0x00  u8      (copied together with the BDA by the "add device" path; not confirmed)
        +0x01  6 bytes BD_ADDR
        +0x1c  u16 LE  class-of-device low half (as read by bt_pdk_deviceEnumNext)
        +0x1e  u16 LE  class-of-device high half / a second field (same function)
        +0x17  u8      flag copied to the UI record's +0xb0 byte (read as "bonded/trusted" here)
        +0x20  string, up to 0x51 bytes  device name
        +0x71  string, up to 0x51 bytes  a second name-like field (alias?)

This is an explicit stand-in for the real inquiry: it never touches the DSP, the RM task or any
HC message, it only writes the device-table record the UI already knows how to display. It
deliberately does NOT also force BTSD.state from "searching" back to "idle": an earlier version of
this module did, and the very next action (cancelling the search) then raised a "No Bluetooth.
Riprovare?" error dialog, i.e. forcing that one field without the real HC command/response
underneath left the firmware's own consistency check confused. So the "Ricerca periferiche in
corso" screen genuinely keeps spinning until the user cancels it by hand; what this module adds is
that a (clearly fictitious: locally-administered BD_ADDR, name "PC (collegamento di prova)") device
is already present afterwards for anything that reads the device table directly, without needing to
be "discovered" through that screen. No physical or virtual Bluetooth adapter was available on this
host (`hciconfig -a` found no controller), so there is no real BlueZ bridge behind it: see
`BluetoothHostBridge` below for the (currently inert) extension point that would read real nearby
devices from BlueZ if a session with a working adapter ever runs this.
"""
from unicorn import UC_HOOK_CODE

STATE = 0x202dcf9
DEVICE_COUNT = 0x202dcd0
DEVICE_TABLE = 0x202dd01
ENTRY_SIZE = 0xca
STATE_SEARCHING = (1, 2, 3)
SEARCH_SITE = 0xe2fdbe        # bluetooth_startDiscovery entry: fires every time Search is pressed
SETTLE_POLLS = 2000           # how many times SEARCH_SITE is otherwise hit before we conclude it

PEER_NAME = b'PC (collegamento di prova)'
PEER_BDA = bytes([0x02, 0x00, 0x00, 0x42, 0x54, 0x01])   # 02:... = locally administered, not a real OUI
PEER_COD = 0x0418  # generic audio/rendering device class


class VirtualPeer:
    """Writes one synthetic, already-reachable device once a search is started."""

    def __init__(self, uc):
        self.uc = uc
        self.added = False
        self.searches = 0
        uc.hook_add(UC_HOOK_CODE, self.on_search, begin=SEARCH_SITE, end=SEARCH_SITE)

    def on_search(self, uc, address, size, _):
        self.searches += 1
        if self.added:
            return
        self.add_device(0)
        self.added = True
        # BTSD.state is deliberately left untouched: forcing it from "searching" straight to "idle"
        # without the real HC command/response underneath left the firmware's own consistency check
        # confused (observed: the next action raised "No Bluetooth. Riprovare?"), so the search
        # screen genuinely keeps spinning until the user cancels it, same as before this module.

    def add_device(self, index):
        uc = self.uc
        base = DEVICE_TABLE + ENTRY_SIZE * index
        uc.mem_write(base + 0x00, b'\x01')
        uc.mem_write(base + 0x01, PEER_BDA)
        uc.mem_write(base + 0x1c, (PEER_COD & 0xffff).to_bytes(2, 'little'))
        uc.mem_write(base + 0x1e, b'\x00\x00')
        uc.mem_write(base + 0x17, b'\x01')
        uc.mem_write(base + 0x20, PEER_NAME.ljust(0x51, b'\0')[:0x51])
        uc.mem_write(base + 0x71, PEER_NAME.ljust(0x51, b'\0')[:0x51])
        count = uc.mem_read(DEVICE_COUNT, 1)[0]
        if count <= index:
            uc.mem_write(DEVICE_COUNT, bytes([index + 1]))

    def report(self):
        return {'searches_seen': self.searches, 'device_added': self.added}


class BluetoothHostBridge:
    """Extension point for a real BlueZ bridge; inert here (no adapter was available to test against).

    A future session with a working Bluetooth controller could replace VirtualPeer.add_device's
    fixed name/BDA/class with the result of a real `bluetoothctl`/D-Bus scan (org.bluez
    Adapter1.StartDiscovery + ObjectManager for Device1 objects), and forward real SCO/A2DP audio
    through a BlueZ media endpoint instead of (or in addition to) the host decoders audio_hle.py
    already uses for the phone's own sounds. Not implemented or tested in this session.
    """
