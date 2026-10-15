"""Run original SSIKYU page crypto routines in an isolated ARM926 instance.

This does not synthesize factory data or bypass a firmware check.
"""
from pathlib import Path
from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import UC_CPU_ARM_926, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR

ROOT = Path(__file__).resolve().parents[1]

class CryptoProbe:
    INPUT = 0x04f00000
    OUTPUT = INPUT + 0x1000
    RETURN = INPUT + 0x2000

    def __init__(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.ctl_set_cpu_model(UC_CPU_ARM_926)
        self.uc.mem_map(0, 0x04000000)
        self.uc.mem_map(self.INPUT, 0x100000)
        self.firmware = next((ROOT/'firmware').glob('*CODE*')).read_bytes()
        self.uc.mem_write(0x5c000, self.firmware[0x24000:])

    def transform(self, data, encrypt=False):
        if len(data) != 512:
            raise ValueError('SSIKYU operates on 512-byte pages')
        u = self.uc
        u.reg_write(UC_ARM_REG_CPSR, 0xd3)
        u.reg_write(UC_ARM_REG_SP, self.INPUT+0xff000)
        u.reg_write(UC_ARM_REG_LR, self.RETURN|1)
        u.mem_write(self.INPUT, data)
        u.reg_write(UC_ARM_REG_R0, self.INPUT)
        u.reg_write(UC_ARM_REG_R1, self.OUTPUT)
        function = 0x70732 if encrypt else 0x706f4
        u.emu_start(function|1, self.RETURN, count=2000000)
        if u.reg_read(UC_ARM_REG_PC) != self.RETURN:
            raise RuntimeError(f'Crypto routine did not return: PC=0x{u.reg_read(UC_ARM_REG_PC):x}')
        return bytes(u.mem_read(self.OUTPUT if encrypt else self.INPUT, 512))

if __name__ == '__main__':
    import json, struct
    probe = CryptoProbe()
    sample = bytes(range(256))*2
    cipher = probe.transform(sample, encrypt=True)
    assert cipher != sample
    assert probe.transform(cipher) == sample
    findings = []
    # Check candidates without claiming that the flashing container is raw NAND.
    for source in [next((ROOT/'firmware').glob('*CODE*')), ROOT/'firmware/en_bootshell_U310R.bin', ROOT/'firmware/u310.nvm']:
        data = source.read_bytes()
        matches = []
        bound = len(data)
        for offset in range(0, bound-511, 512):
            plain = probe.transform(data[offset:offset+512])
            magic = struct.unpack_from('<II', plain)
            if magic in [(0xbec6c0cc,0xbfa5c0cc),(0xbdc9b6f4,0xc4dab5e5)]:
                matches.append(hex(offset))
        findings.append({'file': source.name, 'candidate_pages_tested': bound//512,
                         'encrypted_ssikyu_header_offsets': matches})
    out = ROOT/'analysis/ssikyu_crypto_probe.json'
    out.write_text(json.dumps({'roundtrip_verified': True, 'findings': findings}, indent=2)+'\n')
    print(out)
    print(json.dumps(findings))
