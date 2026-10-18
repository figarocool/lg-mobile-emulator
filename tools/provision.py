"""Install the emulated phone from the user's own original firmware files.

  python3 tools/provision.py FOLDER_OR_ZIP

Steps (each uses the phone's original code; no firmware byte is changed):
  1. identify CODE / MEDIA / MODULE by hash and copy them into firmware/
  2. decode the two EFS images into extracted/
  3. boot the phone on an empty flash (with the synthetic factory block) until its file system is up
  4. install the 129 modules and 550 resource files through the original file-system API
  5. write the country header from the original Flex.ini
  6. save the flash as data/phone.zip (+ data/factory.zip, the copy used by "reset")
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
DATA = ROOT / 'data'
PHONE = DATA / 'phone.zip'
FACTORY = DATA / 'factory.zip'
STATE_VERSION = 2  # bumped when an emulator change makes a flash saved by an older version misbehave (v2: simulated network and SIM)
VERSION_FILE = DATA / 'state_version.json'
BOOT_STEPS = 250_000_000  # instructions: the file system task is ready (checked by the next step)
sys.path.insert(0, str(TOOLS))


def state_outdated():
    """True when the saved phone was written by an older emulator whose stored SIM/network state no longer fits."""
    if not PHONE.exists():
        return False
    try:
        return json.loads(VERSION_FILE.read_text()).get('version', 0) < STATE_VERSION
    except (OSError, ValueError):
        return True


def mark_current():
    DATA.mkdir(exist_ok=True)
    VERSION_FILE.write_text(json.dumps({'version': STATE_VERSION}) + '\n')


def installed():
    return PHONE.exists() and (ROOT / 'extracted/MODULE/manifest.json').exists()


def say(progress, step, total, text):
    progress(f'[{step}/{total}] {text}')


def run_tool(args, progress, quiet=True):
    process = subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, capture_output=True, text=True)
    if process.returncode != 0:
        raise RuntimeError(f'{Path(args[0]).name} è fallito:\n{process.stdout[-800:]}\n{process.stderr[-800:]}')
    return process.stdout


def locate(source, workdir):
    source = Path(source)
    if source.is_file() and zipfile.is_zipfile(source):
        target = Path(workdir) / 'unzipped'
        with zipfile.ZipFile(source) as archive:
            archive.extractall(target)
        source = target
    if not source.is_dir():
        raise ValueError('Indica la cartella (o lo zip) con i file originali del firmware')
    import firmware_profiles
    profile_id, _profile_files, _profile_problems = firmware_profiles.identify(source)
    if profile_id and not firmware_profiles.PROFILES[profile_id]['bootable']:
        profile = firmware_profiles.PROFILES[profile_id]
        raise ValueError(
            f"Rilevato {profile['model']} {profile['version']}: il CODE non è ancora supportato dal boot emulator. "
            'Prepara un profilo isolato con `./u310 prepare-profile <cartella firmware>`; '
            'non sostituire il profilo U310.'
        )
    import firmware_manifest
    found, problems = firmware_manifest.find(source)
    if problems:
        raise ValueError('\n'.join(problems))
    return found


def install(source, progress=print):
    total = 6
    DATA.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='u310-install-') as work:
        work = Path(work)
        say(progress, 1, total, 'Controllo e copio i file del firmware…')
        found = locate(source, work)
        firmware = ROOT / 'firmware'
        firmware.mkdir(exist_ok=True)
        import firmware_manifest
        for role, path in found.items():
            names = {**firmware_manifest.REQUIRED, **firmware_manifest.OPTIONAL}
            shutil.copyfile(path, firmware / names[role]['name'])
        say(progress, 2, total, 'Estraggo moduli e risorse…')
        run_tool([TOOLS / 'extract_efs.py'], progress)
        say(progress, 3, total, 'Primo avvio su flash vuota (circa un minuto)…')
        boot = work / 'boot.zip'
        run_tool([TOOLS / 'emulator.py', '--target', 'amss', '--nand', '--lcd-bus', '--shadow-mmio', '--register-banks',
                  '--timer-irq', '--mmc-clock', '--mdsp-management', '--keypad', '--synthetic-ssikyu', '--fast',
                  '--limit', BOOT_STEPS, '--save-checkpoint', boot], progress)
        say(progress, 4, total, 'Installo i 129 moduli…')
        modules = work / 'modules.zip'
        run_tool([TOOLS / 'install_modules.py', '--resume', boot, '--scope', 'modules', '--fast', '--output', modules], progress)
        say(progress, 4, total, 'Installo le 550 risorse (immagini, suoni, temi)…')
        media = work / 'media.zip'
        run_tool([TOOLS / 'install_modules.py', '--resume', modules, '--scope', 'media', '--fast', '--output', media], progress)
        say(progress, 5, total, 'Imposto il paese di fabbrica…')
        from initialize_flex_country import build
        flex = (ROOT / 'extracted/MEDIA/LGAPP/Media/Flex/Flex.ini').read_bytes()
        match = re.search(rb'^FLEX_COUNTRY_CODE=(\d+)\s*$', flex, re.MULTILINE)
        if not match:
            raise RuntimeError('Flex.ini senza FLEX_COUNTRY_CODE')
        nand, _report = build(media, int(match[1]))
        say(progress, 6, total, 'Salvo il telefono…')
        with zipfile.ZipFile(media) as source_zip, zipfile.ZipFile(PHONE.with_suffix('.tmp'), 'w', zipfile.ZIP_DEFLATED) as out:
            out.writestr('metadata.json', json.dumps({'nand': json.loads(source_zip.read('metadata.json'))['nand']}))
            out.writestr('nand.bin', bytes(nand))
            out.writestr('nand_spare.bin', source_zip.read('nand_spare.bin'))
        PHONE.with_suffix('.tmp').replace(PHONE)
        shutil.copyfile(PHONE, FACTORY)
        (DATA / 'install.json').write_text(json.dumps({'firmware': {r: p.name for r, p in found.items()}}, indent=2) + '\n')
        mark_current()
    progress('Installazione completata. Avvia il telefono con: python3 tools/u310.py run')


def uninstall(progress=print, keep_firmware=False):
    """Delete the installed phone: flash, copies of the firmware and extracted resources (SIM and microSD files stay)."""
    for path in (PHONE, FACTORY, PHONE.with_suffix('.bak'), DATA / 'install.json', VERSION_FILE):
        path.unlink(missing_ok=True)
    targets = [ROOT / 'extracted'] + ([] if keep_firmware else [ROOT / 'firmware'])
    for folder in targets:
        shutil.rmtree(folder, ignore_errors=True)
    progress('Telefono disinstallato: flash, risorse estratte' + ('' if keep_firmware else ' e copie del firmware') + ' eliminati.')


def reinstall(source, progress=print):
    """Wipe everything and run the whole installation again from the given firmware folder or zip."""
    uninstall(progress)
    install(source, progress)


def reset(progress=print):
    if not FACTORY.exists():
        raise RuntimeError('Nessuna copia di fabbrica: esegui prima l\'installazione')
    shutil.copyfile(FACTORY, PHONE)
    mark_current()
    progress('Telefono riportato allo stato di fabbrica.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source', type=Path, help='Cartella o zip con i file originali (CODE, MEDIA, MODULE)')
    args = parser.parse_args()
    try:
        install(args.source)
    except (ValueError, RuntimeError) as exc:
        print(f'Errore: {exc}', file=sys.stderr)
        sys.exit(1)
