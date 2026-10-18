"""Hardware-side U880 UART bring-up tests; not a complete SIM boot test."""
import unittest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_PC
from uim_uart import UimUart, COMMAND, STATUS, RECEIVE, DEFAULT_ATR
class Timer:
 def __init__(self):self.sources=[]
 def raise_source(self,source):self.sources.append(source)
class TestU880Uim(unittest.TestCase):
 def setUp(self):
  self.u=Uc(UC_ARCH_ARM,UC_MODE_ARM);self.u.mem_map(0x84000000,0x1000);self.timer=Timer()
 def write(self,model,value):model.access(self.u,17,COMMAND,4,value,None)
 def test_reset_supplies_atr_and_interrupt(self):
  m=UimUart(self.u,self.timer,atr_poll_pc=None,atr_on_reset=True)
  self.write(m,1)
  self.assertEqual(bytes(m.rx),DEFAULT_ATR);self.assertEqual(self.timer.sources,[28]);self.assertTrue(m.delivered)
  self.write(m,0x10);self.assertFalse(m.rx)
 def test_u310_default_does_not_change(self):
  m=UimUart(self.u,self.timer)
  self.write(m,1);self.assertFalse(m.rx);self.assertFalse(m.delivered);self.assertFalse(self.timer.sources)
if __name__=='__main__':unittest.main()
