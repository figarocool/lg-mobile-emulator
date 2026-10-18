"""Initialize one normal-boot UI preference in a disposable U880 simulation.

Original V10b UI database APIs read/write record 0x11a, whose flag selects
hidden-reset boot in the simulated filesystem.
The caller must explicitly opt into the synthetic configuration experiment.
"""
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_LR, UC_ARM_REG_PC)

class UiNormalBootFixture:
    KIND = 'synthetic_ui_normal_boot_preference'
    RETURN = 0x04f01000
    BUFFER = 0x04f02000
    STOP = 'debugger: original UI preference API returned'

    def __init__(self):
        self.calls = 0
        self.events = []

    def setup(self, uc, state):
        self.context = uc.context_save()
        self.tcb = bytes(uc.mem_read(0x1c3ded4, 4))
        if int.from_bytes(self.tcb, 'little') != 0x1e34884:
            raise ValueError('UI fixture requires the original UI task context')
        def returned(machine, address, size, _):
            state['stop'] = self.STOP
            machine.emu_stop()
        uc.hook_add(UC_HOOK_CODE, returned, begin=self.RETURN, end=self.RETURN)
        self.prepare(uc)

    def prepare(self, uc):
        uc.mem_write(self.BUFFER, bytes(8))
        uc.reg_write(UC_ARM_REG_R0, 0x11a)
        uc.reg_write(UC_ARM_REG_R1, self.BUFFER)
        uc.reg_write(UC_ARM_REG_R2, 0)
        uc.reg_write(UC_ARM_REG_R3, 0)
        uc.reg_write(UC_ARM_REG_LR, self.RETURN|1)
        uc.reg_write(UC_ARM_REG_PC, 0xc5a63b if self.calls == 1 else 0xc5a5bd)

    def finish(self, uc, state):
        if bytes(uc.mem_read(0x1c3ded4, 4)) != self.tcb:
            raise ValueError('UI preference call returned in a different task')
        result = uc.reg_read(UC_ARM_REG_R0)
        flag = struct.unpack('<I', bytes(uc.mem_read(self.BUFFER+4, 4)))[0]
        event = dict(operation='write' if self.calls == 1 else 'read',
                     item='0x11a', result=hex(result), flag=flag)
        self.events.append(event)
        expected = 0x11a if self.calls == 1 else 1
        if result != expected or (self.calls == 0 and flag != 1) or (self.calls == 2 and flag != 0):
            raise ValueError('Unexpected UI factory preference state: '+str(event))
        uc.context_restore(self.context)
        self.calls += 1
        if self.calls == 3:
            state['ui_normal_boot_fixture'] = dict(
                kind=self.KIND, calls=self.events,
                scope='Original UI database APIs in simulated NAND only')
            return False
        self.prepare(uc)
        return True
