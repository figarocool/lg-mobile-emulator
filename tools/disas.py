import struct,sys
from task_stack import load
from capstone import *
read=load(sys.argv[1]); md=Cs(CS_ARCH_ARM,CS_MODE_THUMB); md.skipdata=True
a=int(sys.argv[2],16); n=int(sys.argv[3],16)
def cstr(x):
    try:
        s=read(x,50).split(b'\0')[0]
        return s.decode('latin1') if len(s)>3 and all(32<=c<127 for c in s) else ''
    except Exception: return ''
for i in md.disasm(read(a,n),a):
    e=''
    if i.mnemonic=='ldr' and 'pc' in i.op_str:
        la=((i.address+4)&~3)+int(i.op_str.split('#')[1].rstrip(']'),16); w=struct.unpack('<I',read(la,4))[0]; e='  ; =%#x %s'%(w,cstr(w) if 0x10000<w<0x2000000 else '')
    print(hex(i.address),i.mnemonic,i.op_str,e)
