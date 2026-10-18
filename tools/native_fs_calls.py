"""Debugger-assisted calls to the original guest filesystem APIs.

No firmware instructions or API return values are replaced. Each request
runs the original API, scheduler and FS task. At its return breakpoint the
caller's original CPU context is restored, then the next request is issued.
This is an import/debug facility, not a hardware model or normal phone boot.
"""
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
import hashlib
import struct


class NativeFsCalls:
    KIND = 'native_fs_import'
    NAME = 0x04f00000
    RESPONSE = 0x04f00100
    PARAMETERS = 0x04f00200
    RETURN = 0x04f01000
    BUFFER = 0x04000000
    STOP = 'debugger: native filesystem API returned'

    API = dict(open=0x161ebcd, read=0x161ec6d, write=0x161ecb7,
               close=0x161ec2f, test=0x161f2a5, mkdir=0x161f21d,
               nv_read=0x10d219b, nv_write=0x10d219b)

    def __init__(self, requests, *, api=None, current_tcb=0x19a3f18):
        self.requests = requests
        self.calls = 0
        self.api = self.API if api is None else api
        self.current_tcb = current_tcb

    def setup(self, uc, state):
        self.uc = uc
        self.context = uc.context_save()
        self.tcb = bytes(uc.mem_read(self.current_tcb, 4))
        def returned(u, address, size, _):
            state['stop'] = self.STOP
            u.emu_stop()
        uc.hook_add(UC_HOOK_CODE, returned, begin=self.RETURN, end=self.RETURN)
        self.prepare(next(self.requests))

    def prepare(self, request):
        self.request = request
        u = self.uc
        op = request['operation']
        path = request.get('path', '')
        raw = path.encode('ascii')+b'\x00'
        if len(raw) > 256 or b'\x00' in raw[:-1]:
            raise ValueError('Invalid import path')
        u.mem_write(self.NAME, raw)
        u.mem_write(self.RESPONSE, b'\xcc'*32)
        u.mem_write(self.PARAMETERS, b'\x00'*16)
        u.reg_write(UC_ARM_REG_R0, self.NAME)
        u.reg_write(UC_ARM_REG_R1, 1)
        u.reg_write(UC_ARM_REG_R2, 0)
        u.reg_write(UC_ARM_REG_R3, self.RESPONSE)
        u.reg_write(UC_ARM_REG_LR, self.RETURN | 1)
        if op in ('create', 'open', 'read', 'write'):
            sp = u.reg_read(UC_ARM_REG_SP)-16
            u.reg_write(UC_ARM_REG_SP, sp)
            u.mem_write(sp, self.RESPONSE.to_bytes(4, 'little'))
            u.reg_write(UC_ARM_REG_R1, 0 if op == 'create' else 2)
            u.reg_write(UC_ARM_REG_R2, self.PARAMETERS)
            u.reg_write(UC_ARM_REG_R3, 0)
            pc = self.api['open']
            if op in ('read', 'write'):
                data = request['data'] if op == 'write' else b'\xcc'*request['length']
                if len(data) > 0x00d00000:
                    raise ValueError('File exceeds import buffer')
                u.mem_write(self.BUFFER, data)
                u.reg_write(UC_ARM_REG_R0, request['handle'])
                u.reg_write(UC_ARM_REG_R1, self.BUFFER)
                u.reg_write(UC_ARM_REG_R2, len(data))
                pc = self.api[op]
        elif op == 'close':
            u.reg_write(UC_ARM_REG_R0, request['handle'])
            u.reg_write(UC_ARM_REG_R1, 0)
            u.reg_write(UC_ARM_REG_R2, self.RESPONSE)
            pc = self.api[op]
        elif op == 'test':
            u.reg_write(UC_ARM_REG_R1, request.get('kind', 1))
            pc = self.api[op]
        elif op == 'mkdir':
            u.reg_write(UC_ARM_REG_R1, 0)
            u.reg_write(UC_ARM_REG_R2, self.RESPONSE)
            pc = self.api[op]
        elif op in ('nv_read', 'nv_write'):
            u.mem_write(self.RESPONSE, b'\x00'*32)
            data = request.get('data', b'')
            if len(data) > 128:
                raise ValueError('NV probe payload exceeds verified buffer size')
            u.mem_write(self.BUFFER, data.ljust(128, b'\x00'))
            u.mem_write(self.RESPONSE+4, struct.pack('<HHI', request['item'], int(op == 'nv_write'), self.BUFFER))
            u.reg_write(UC_ARM_REG_R0, self.RESPONSE)
            pc = self.api[op]
        else:
            raise ValueError(f'Unsupported native operation: {op}')
        u.reg_write(UC_ARM_REG_PC, pc)

    def finish(self, uc, state):
        if state['stop'] != self.STOP:
            raise ValueError(f'Native request did not finish: {state["stop"]}, PC={uc.reg_read(UC_ARM_REG_PC):x}')
        if bytes(uc.mem_read(self.current_tcb, 4)) != self.tcb:
            raise ValueError('Native request returned in a different task')
        raw = bytes(uc.mem_read(self.RESPONSE, 32))
        result = {'status': raw[0], 'present': raw[1],
                  'handle': int.from_bytes(raw[2:4], 'little'),
                  'count': int.from_bytes(raw[4:8], 'little')}
        if self.request['operation'] in ('nv_read', 'nv_write'):
            result = {'item': self.request['item'], 'status': int.from_bytes(raw[24:26], 'little'),
                      'sha256': hashlib.sha256(bytes(uc.mem_read(self.BUFFER, 128))).hexdigest()}
        if self.request['operation'] == 'read':
            data = bytes(uc.mem_read(self.BUFFER, self.request['length']))
            result['sha256'] = hashlib.sha256(data).hexdigest()
        uc.context_restore(self.context)
        self.calls += 1
        try:
            request = self.requests.send(result)
        except StopIteration:
            state['stop'] = 'native filesystem import complete'
            state['native_fs_calls'] = self.calls
            return False
        self.prepare(request)
        return True
