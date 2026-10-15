#!/usr/bin/env python3
"""LG U310 emulator launcher.

  u310.py install FOLDER   one-time installation from your original firmware files
  u310.py run              power the phone on (window)
  u310.py reset            back to the factory state
  u310.py info             what is installed
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import provision  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    install = sub.add_parser('install', help='Installa il telefono dai file originali del firmware')
    install.add_argument('source', type=Path)
    run = sub.add_parser('run', help='Accende il telefono')
    run.add_argument('extra', nargs=argparse.REMAINDER, help='Opzioni passate alla finestra (--pin, --flip-closed, ...)')
    sub.add_parser('reset', help='Ripristina lo stato di fabbrica')
    sub.add_parser('uninstall', help='Elimina flash, risorse e copie del firmware')
    again = sub.add_parser('reinstall', help='Cancella tutto e ripete l\'installazione da capo')
    again.add_argument('source', type=Path)
    sd = sub.add_parser('sd', help='Gestisce le immagini microSD')
    sd.add_argument('action', choices=['create', 'format', 'info', 'copy-in', 'copy-out', 'ls'])
    sd.add_argument('image', type=Path)
    sd.add_argument('args', nargs='*', help='create: dimensione in MB [etichetta]; copy-in: file...; copy-out: cartella')
    sub.add_parser('info', help='Mostra lo stato dell\'installazione')
    args = parser.parse_args(argv)
    try:
        if args.command == 'install':
            provision.install(args.source)
        elif args.command == 'reset':
            provision.reset()
        elif args.command == 'uninstall':
            provision.uninstall()
        elif args.command == 'reinstall':
            provision.reinstall(args.source)
        elif args.command == 'sd':
            import sd_card
            if args.action == 'create':
                sd_card.create_image(args.image, int(args.args[0]), args.args[1] if len(args.args) > 1 else 'U310SD')
                print(sd_card.info(args.image))
            elif args.action == 'format':
                sd_card.format_image(args.image, args.args[0] if args.args else 'U310SD')
            elif args.action == 'info':
                print(sd_card.info(args.image))
            elif args.action == 'copy-in':
                sd_card.copy_in(args.image, args.args)
            elif args.action == 'copy-out':
                sd_card.copy_out(args.image, args.args[0])
            else:
                print(sd_card.listing(args.image))
        elif args.command == 'info':
            if not provision.installed():
                print('Telefono non installato. Esegui: u310.py install <cartella firmware>')
                return 1
            print('Telefono installato:', provision.PHONE)
            info = provision.DATA / 'install.json'
            if info.exists():
                print(json.dumps(json.loads(info.read_text()), indent=2))
        elif args.command == 'run':
            return subprocess.call([sys.executable, str(TOOLS / 'window.py'), *args.extra])
    except (ValueError, RuntimeError) as exc:
        print(f'Errore: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
