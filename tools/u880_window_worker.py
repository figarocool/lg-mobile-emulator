"""U880 V10b window backend; actual firmware resumed from isolated UI state."""
import argparse
import hashlib
import json
import signal
import zipfile
from pathlib import Path
from u880_machine import run
ROOT=Path(__file__).resolve().parents[1]
SEED=ROOT/'data/u880-v10b/resources.zip'
def main():
 p=argparse.ArgumentParser();p.add_argument('--live-dir',type=Path,required=True);p.add_argument('--keys-file',type=Path,required=True);p.add_argument('--state',type=Path,required=True);p.add_argument('--flip',choices=['open','closed'],default='open');p.add_argument('--virtual-sim',action='store_true');p.add_argument('--limit',type=int,default=10**12);a=p.parse_args()
 if not SEED.is_file() or not (ROOT/'data/u880-v10b/amss.bin').is_file():
  raise ValueError('Install U880 first: python u310 install FOLDER --profile u880-v10b-h3g [--key-file KEY]')
 code=(ROOT/'data/u880-v10b/amss.bin').read_bytes()
 if hashlib.sha256(code).hexdigest()!='95dfa53aee43bd97aba158878e655adeb0d9b3fc0f02c13efb30319c0a29f9d0':raise ValueError('U880 V10b firmware mismatch')
 stopped=False
 def stop(*_):
  nonlocal stopped
  stopped=True
 for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)
 a.state.parent.mkdir(parents=True,exist_ok=True)
 temporary=a.state.with_suffix('.pending.zip')
 raw_nand=None
 resume=a.state if a.state.exists() else None
 if resume is None:
  with zipfile.ZipFile(SEED) as z:raw_nand=z.read('nand.bin')
 if a.virtual_sim:
  import os
  os.environ['U310_PIN']='off'
  os.environ.pop('U310_SIM',None)  # U880 must not write an existing U310 SIM profile
  if not a.state.exists():
   with zipfile.ZipFile(SEED) as z:raw_nand=z.read('nand.bin')
   resume=None
 report=run(code,a.limit,shadow=True,zero_ram=True,block_trace=True,banks=True,nand=True,nand_image=raw_nand,lcd=True,live_dir=a.live_dir,mmc=True,irq=True,keypad=True,keys_file=a.keys_file,synthetic_ssikyu=False,page_crypto=(0xdcdf8,0xdce36),synthetic_country=None,dynamic_code=True,fast=True,flip=a.flip=='open',fatal_entries=(0xbd1692,0xbd1490),resume=resume,save_checkpoint=temporary,uim_card=a.virtual_sim,stop_requested=lambda:stopped)
 if report.get('unicorn_error') or report.get('fatal'):
  temporary.replace(a.state.with_suffix('.failed.zip'))
 else:
  temporary.replace(a.state)
 report['virtual_sim_enabled']=a.virtual_sim
 report.update(simulation='U880 original firmware; synthetic factory/UI provisioning; experimental U880 USIM transport; no U880 radio model',window_backend=True)
 (a.live_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(report['stop'],report['pc'],flush=True)
 if report.get('unicorn_error'):raise SystemExit(1)
if __name__=='__main__':main()
