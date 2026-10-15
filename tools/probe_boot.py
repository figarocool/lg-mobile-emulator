"""Limited ARM bootloader probe; unmapped hardware stops execution."""
from pathlib import Path
from collections import deque
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_INVALID
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_CPSR

ROOT = Path(__file__).resolve().parents[1]
data = (ROOT / 'firmware/BOOT_LOADER_U310.bin').read_bytes()
# Hypothesis from absolute internal pointers: 0xffff02dd, 0xffff0950.
BASE = 0xffff0000
uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
uc.mem_map(BASE, 0x10000)
uc.mem_write(BASE, data)
uc.reg_write(UC_ARM_REG_CPSR, 0xd3)
trace = deque(maxlen=40)
events = []
arm = Cs(CS_ARCH_ARM, CS_MODE_ARM)
thumb = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def code_hook(u, address, size, _):
    md = thumb if u.reg_read(UC_ARM_REG_CPSR) & 0x20 else arm
    ins = next(md.disasm(bytes(u.mem_read(address, size)), address), None)
    trace.append(f'{address:08x}: {ins.mnemonic} {ins.op_str}' if ins else hex(address))

def invalid_hook(u, access, address, size, value, _):
    events.append(f'Unmapped access type={access} address=0x{address:08x} size={size} value=0x{value:x}')
    return False  # Do not invent hardware behavior.

uc.hook_add(UC_HOOK_CODE, code_hook)
uc.hook_add(UC_HOOK_MEM_INVALID, invalid_hook)
try:
    uc.emu_start(BASE, BASE + len(data), count=10000)
except UcError as exc:
    events.append(str(exc))
output = '\n'.join([
    'Experimental base: 0xffff0000; only bootloader memory mapped.',
    'This executes instructions, not the complete phone firmware.',
    *trace, *events, f'Final PC: 0x{uc.reg_read(UC_ARM_REG_PC):08x}',
]) + '\n'
(ROOT / 'analysis/boot_probe.txt').write_text(output)
print(output)
