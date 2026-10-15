"""Read-only view of the REX task layout recovered from this U310 firmware."""
import struct
from unicorn import UcError

def inspect_rex(uc):
    def read32(address):
        return int.from_bytes(uc.mem_read(address, 4), 'little')

    result = {'current_tcb_global': '0x019a3f18', 'tasks': [],
              'layout': 'inferred for this firmware, not a universal REX ABI'}
    try:
        current = read32(0x019a3f18)
        result['current_tcb'] = hex(current)
        address = 0x019a4104
        seen = set()
        for _ in range(128):
            if address in seen or not 0x01800000 <= address < 0x03400000:
                break
            seen.add(address)
            data = bytes(uc.mem_read(address, 0x80))
            name = data[0x60:0x6c].split(b'\0')[0].decode('ascii', 'replace').strip()
            if not name:
                break
            values = struct.unpack_from('<6I', data)
            result['tasks'].append({'address': hex(address), 'name': name,
                'current': address == current, 'saved_sp': hex(values[0]),
                'signals': hex(values[3]), 'wait_signals': hex(values[4]),
                'priority': values[5]})
            address = struct.unpack_from('<I', data, 0x28)[0]
        result['timers'] = []
        address = read32(0x019a3ed0)
        seen = set()
        for _ in range(128):
            if address == 0x019a3eb4 or address in seen or not 0x01800000 <= address < 0x03400000:
                break
            seen.add(address)
            values = struct.unpack('<7I', bytes(uc.mem_read(address, 28)))
            result['timers'].append({'address': hex(address), 'delta': values[2],
                'tcb': hex(values[3]), 'signals': hex(values[4]), 'callback': hex(values[5])})
            address = values[0]
    except UcError as exc:
        result['unavailable'] = str(exc)
    return result
