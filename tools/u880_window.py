#!/usr/bin/python3
"""U880 V10b frontend sharing U310 display/keypad widgets, isolated backend/state."""
import os
import subprocess
import sys
from pathlib import Path
from window import EmulatorWindow, Gtk, GLib, ROOT
class U880Window(EmulatorWindow):
 def __init__(self,virtual_sim=True,cold_boot=False):
  self.virtual_sim=virtual_sim
  self.cold_boot=cold_boot
  super().__init__(None,True)
  self.set_title('LG U880 V10b — '+('avvio con USIM virtuale' if self.virtual_sim else 'emulatore sperimentale'))
  self.nes_controls_button.set_sensitive(False)
 def build_menu(self):
  return Gtk.Label(label='LG U880 V10b')
 def on_settings(self,_button):
  self.message(Gtk.MessageType.INFO,'U880 V10b','USIM virtuale disponibile. La rete radio U880 non e ancora emulata. Stato separato da U310.')
 def start(self):
  live=self.work/'live';live.mkdir(exist_ok=True)
  state=(self.work/'cold-usim.zip' if self.cold_boot else ROOT/'data/u880-v10b/usim-window.zip') if self.virtual_sim else ROOT/'data/u880-v10b/window.zip'
  args=[sys.executable,str(ROOT/'tools/u880_window_worker.py'),'--live-dir',str(live),'--keys-file',str(self.keys_file),'--state',str(state),'--flip','open' if self.flip_open else 'closed']
  if self.virtual_sim:args+=['--virtual-sim']
  self.child=subprocess.Popen(args,cwd=ROOT,stdout=self.log,stderr=self.log)
 def poll(self):
  if self.closed:return False
  self.show('main.ppm',self.main,self.scale);self.show('sub.ppm',self.sub,1)
  if self.child.poll() is not None:
   import json
   report=self.work/'live/report.json'
   try:
    data=json.loads(report.read_text());reason=data.get('stop','fermo')
    self.status.set_text('U880: '+reason+' a '+data.get('pc','?'))
   except (OSError,ValueError):self.status.set_text('U880 fermo: dettagli in analysis/window.log')
  elif (self.work/'live/main.ppm').exists():self.status.set_text('U880 — USIM virtuale in prova' if self.virtual_sim else 'U880 in esecuzione — SIM/rete non emulate')
  else:self.status.set_text('Caricamento sistema U880…')
  return True
if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group();group.add_argument('--virtual-sim',dest='virtual_sim',action='store_true');group.add_argument('--without-sim',dest='virtual_sim',action='store_false');parser.set_defaults(virtual_sim=True);parser.add_argument('--cold-boot',action='store_true');args=parser.parse_args()
 w=U880Window(args.virtual_sim,args.cold_boot)
 import signal
 for sig in (signal.SIGTERM,signal.SIGINT):GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,sig,w.close)
 Gtk.main()
