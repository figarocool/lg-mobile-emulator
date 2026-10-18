#!/usr/bin/env python3
"""Prepare an isolated local firmware profile without touching the U310 install.

This copies the original CODE/MEDIA/MODULE and extracts EFS2 under instances/.
It does not flash a phone, create a NAND, or claim that opaque CODE can boot.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import extract_efs
import firmware_profiles


def prepare(source, instance_dir=None):
    profile_id, found, problems = firmware_profiles.identify(source)
    if problems:
        raise ValueError('\n'.join(problems))
    profile = firmware_profiles.PROFILES[profile_id]
    instance_dir = Path(instance_dir) if instance_dir else ROOT / 'instances' / profile_id
    if not instance_dir.is_absolute():
        instance_dir = ROOT / instance_dir
    if instance_dir.exists() and any(instance_dir.iterdir()):
        raise FileExistsError(f"Profilo già presente; non lo sovrascrivo: {instance_dir}")
    instance_dir.parent.mkdir(parents=True, exist_ok=True)
    if instance_dir.exists():
        instance_dir.rmdir()  # only an empty directory was allowed above
    staging = Path(tempfile.mkdtemp(prefix=f'.{instance_dir.name}.stage-', dir=instance_dir.parent))
    try:
        firmware_dir = staging / 'firmware'
        firmware_dir.mkdir()
        output_files = {}
        for role, spec in profile['files'].items():
            destination = firmware_dir / spec['name']
            shutil.copyfile(found[role], destination)
            output_files[role] = {'path': str(destination.relative_to(staging)),
                                  'size': destination.stat().st_size,
                                  'sha256': firmware_profiles.sha256(destination)}

        extracted = {}
        for role in ('MEDIA', 'MODULE'):
            destination = staging / 'extracted' / role
            manifest = extract_efs.extract(firmware_dir / profile['files'][role]['name'], destination)
            files = [item for item in manifest if item['kind'] == 'file']
            extracted[role] = {
                'records': len(manifest),
                'files': len(files),
                'directories': len(manifest) - len(files),
                'pxo_files': sum(item['path'].lower().endswith('.pxo') for item in files),
                'manifest': str(destination.relative_to(staging) / 'manifest.json'),
            }

        state = {
            'profile_id': profile_id,
            'model': profile['model'],
            'version': profile['version'],
            'instance_dir': str(instance_dir),
            'files': output_files,
            'efs2_extracted': extracted,
            'bootable': profile['bootable'],
            'status': ('prepared' if profile['bootable'] else
                       'prepared-board-model-required' if profile.get('code_decoder') else
                       'prepared-codec-required'),
        }
        if profile.get('code_decoder'):
            state['code_decoder'] = profile['code_decoder']
        if not profile['bootable']:
            state['boot_blocker'] = profile['boot_blocker']
        (staging / 'profile.json').write_text(json.dumps(state, indent=2) + '\n')
        os.replace(staging, instance_dir)
        return state
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Cartella con i file originali CODE/MEDIA/MODULE')
    parser.add_argument('--instance-dir', type=Path, help='Destinazione separata; per default instances/<profilo>')
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.source, args.instance_dir), indent=2))
    except (ValueError, FileExistsError) as error:
        print(f'Errore: {error}', file=sys.stderr)
        raise SystemExit(1)
