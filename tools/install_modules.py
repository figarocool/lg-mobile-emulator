"""Install original MODULE and MEDIA through the original guest filesystem APIs.

Maps the MODULE staging path /UPLOAD/Pxo to the UI's /LGAPP/Pxo path.
Writes only a new simulated NAND/checkpoint. Every installed file is reopened
and read by the original guest API; count and SHA256 must match the source.
MEDIA preserves original paths and creates directories through native APIs.
NV restoration is not implemented here.
"""
import argparse
import hashlib
import json
from pathlib import Path
from emulator import ROOT, run
from native_fs_calls import NativeFsCalls


def install_requests(files, installed, category='MODULE', directories=()):
    for directory in directories:
        result = yield {'operation': 'test', 'path': directory, 'kind': 0}
        if result['status'] != 0:
            raise ValueError(f'{directory}: directory query status {result["status"]}')
        if not result['present']:
            result = yield {'operation': 'mkdir', 'path': directory}
            if result['status'] != 0:
                raise ValueError(f'{directory}: mkdir status {result["status"]}')
    for index, source in enumerate(files, 1):
        path = 'LGAPP/Pxo/'+source.name if category == 'MODULE' else source.relative_to(ROOT/'extracted/MEDIA').as_posix()
        payload = source.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        def check(result, action):
            if result['status'] != 0:
                raise ValueError(f'{path}: {action} status {result["status"]}')
        result = yield {'operation': 'test', 'path': path}
        check(result, 'test')
        if not result['present']:
            result = yield {'operation': 'create', 'path': path}
            check(result, 'create')
            handle = result['handle']
            result = yield {'operation': 'write', 'handle': handle, 'data': payload}
            check(result, 'write')
            if result['count'] != len(payload):
                raise ValueError(f'{path}: short write')
            result = yield {'operation': 'close', 'handle': handle}
            check(result, 'close')
        result = yield {'operation': 'open', 'path': path}
        check(result, 'reopen')
        handle = result['handle']
        result = yield {'operation': 'read', 'handle': handle, 'length': len(payload)}
        check(result, 'read')
        if result['count'] != len(payload) or result['sha256'] != digest:
            raise ValueError(f'{path}: original guest readback differs from source')
        result = yield {'operation': 'close', 'handle': handle}
        check(result, 'close read')
        installed.append({'path': path, 'source': str(source.relative_to(ROOT)),
                          'size': len(payload), 'sha256': digest,
                          'verified_by_original_guest_read': True})
        print(f'{index}/{len(files)} verified: {path}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path, default=ROOT/'analysis/amss_fs_compat.zip')
    parser.add_argument('--only', help='One exact module filename, for a bounded validation')
    parser.add_argument('--scope', choices=['modules', 'media'], default='modules')
    parser.add_argument('--output', type=Path, default=ROOT/'analysis/amss_modules_installed.zip')
    parser.add_argument('--limit', type=int, default=1000000000)
    parser.add_argument('--fast', action='store_true', help='Run in fast chunk mode (no per-block hooks)')
    args = parser.parse_args()
    category = 'MODULE' if args.scope == 'modules' else 'MEDIA'
    manifest = json.loads((ROOT/'extracted'/category/'manifest.json').read_text())
    if category == 'MODULE':
        files = sorted((ROOT/'extracted/MODULE/UPLOAD/Pxo').glob('*'))
    else:
        files = [ROOT/'extracted/MEDIA'/entry['path'].lstrip('/') for entry in manifest if entry['kind'] == 'file']
    files = [f for f in files if f.is_file() and (not args.only or f.name == args.only)]
    if not files:
        parser.error('No modules selected')
    expected = {entry['path']: entry['sha256'] for entry in manifest if entry['kind'] == 'file'}
    for source in files:
        key = '/UPLOAD/Pxo/'+source.name if category == 'MODULE' else '/'+source.relative_to(ROOT/'extracted/MEDIA').as_posix()
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected[key]:
            raise ValueError(f'Source file differs from extracted manifest: {source.name}')
    installed = []
    directories = sorted({str(parent) for source in files for parent in source.relative_to(ROOT/'extracted/MEDIA').parents if str(parent) != '.'}, key=lambda p: (p.count('/'), p)) if category == 'MEDIA' else []
    session = NativeFsCalls(install_requests(files, installed, category, directories))
    state = run('amss', True, args.limit, True, lcd=True, banks=True, irq=True,
                mmc=True, block_trace=not args.fast, fast=args.fast, mdsp_management=True, keypad=True,
                resume=args.resume, save_checkpoint=args.output,
                debug_setup=session.setup, debug_finish=session.finish)
    report = {'kind': f'debugger-assisted native {category} installation', 'files': installed,
              'checkpoint': str(args.output), 'calls': session.calls,
              'instructions': state['instructions'],
              'limitations': [f'{category} import only; original phone NV not restored',
                              'not a hardware flashing protocol or proof of complete emulation']}
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'Installed and verified {len(installed)} files. Checkpoint: {args.output}')
