"""List debug-message strings sent by Thumb code in an address range (msg struct: fmt pointer at +8)."""
import struct, sys
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from task_stack import load

MSG_SEND = {0x7c0654, 0xeee1fc, 0x7c07dc, 0xeee210}


def cstr(read, address):
    try:
        return read(address, 90).split(b'\0')[0].decode('latin1')
    except Exception:
        return '?'


def messages(read, begin, end):
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.skipdata = True
    literal = {}
    for i in md.disasm(read(begin, end - begin), begin):
        if i.mnemonic == 'ldr' and 'pc' in i.op_str and i.op_str.startswith('r0'):
            off = int(i.op_str.split('#')[1].rstrip(']'), 16)
            literal = {'base': struct.unpack('<I', read(((i.address + 4) & ~3) + off, 4))[0], 'add': 0}
        elif i.mnemonic == 'adds' and i.op_str.startswith('r0, #') and literal:
            literal['add'] += int(i.op_str.split('#')[1], 16)
        elif i.mnemonic == 'subs' and i.op_str.startswith('r0, #') and literal:
            literal['add'] -= int(i.op_str.split('#')[1], 16)
        elif i.mnemonic == 'blx' and literal:
            try:
                target = int(i.op_str.lstrip('#'), 16)
            except ValueError:
                continue
            if target in MSG_SEND:
                struct_address = literal['base'] + literal['add']
                try:
                    fmt = struct.unpack('<I', read(struct_address + 8, 4))[0]
                    yield i.address, cstr(read, fmt)
                except Exception:
                    pass
            literal = {}


if __name__ == '__main__':
    read = load(sys.argv[1])
    for address, text in messages(read, int(sys.argv[2], 16), int(sys.argv[3], 16)):
        print(hex(address), text)
