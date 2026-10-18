"""Firmware selection for the shared emulator; never loads U880 with U310 addresses."""
from pathlib import Path
import json

from firmware_profiles import PROFILES, sha256

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = 'u310-v10a-h3g'
U880_FATAL_ENTRIES = {'u880-v10b-h3g': (0xbd1692, 0xbd1490),
                     'u880-v10a-h3g': (0xbcfcc2, 0xbcfac0)}
U880_PAGE_CRYPTO = {'u880-v10b-h3g': (0xdcdf8, 0xdce36),
                    'u880-v10a-h3g': (0xdcad0, 0xdcb0e)}
U880_MANAGER_OPEN_RETURN = {'u880-v10b-h3g': 0xcc4e8, 'u880-v10a-h3g': 0xcc3f4}


def resolve_instance(profile_id, instance=None):
    if profile_id not in PROFILES:
        raise ValueError(f'Profilo sconosciuto: {profile_id}')
    if instance is not None:
        candidates = [Path(instance)]
    else:
        candidates = [p.parent for p in sorted((ROOT/'instances').glob('*/profile.json'))
                      if json.loads(p.read_text()).get('profile_id') == profile_id]
    if len(candidates) != 1:
        raise ValueError(f'Specificare --instance: trovate {len(candidates)} istanze per {profile_id}')
    folder = candidates[0].resolve()
    state = json.loads((folder/'profile.json').read_text())
    if state.get('profile_id') != profile_id:
        raise ValueError('Il profilo richiesto non corrisponde all’istanza')
    return folder, state


def load_u880(profile_id, instance=None, key_file=None):
    from decrypt_u880_code import DEFAULT_KEY, PREFIX, decrypt, validate_vectors
    profile = PROFILES.get(profile_id)
    if profile is None or profile['model'] != 'LG U880':
        raise ValueError(f'Profilo U880 richiesto: {profile_id}')
    folder, _ = resolve_instance(profile_id, instance)
    # Identify the actual CODE by its hash, not an arbitrary path from a manifest.
    spec = profile['files']['CODE']
    code = folder/'firmware'/spec['name']
    if sha256(code) != spec['sha256']:
        raise ValueError('SHA-256 CODE non corrisponde al profilo selezionato')
    key_path = Path(key_file) if key_file is not None else DEFAULT_KEY
    if not key_path.is_file():
        raise ValueError('Chiave locale U880 mancante: specificare --key-file')
    plain = decrypt(code.read_bytes(), key_path.read_bytes())
    vectors = validate_vectors(plain)
    return plain[PREFIX:], {
        'profile_id': profile_id, 'model': profile['model'], 'version': profile['version'],
        'instance_dir': str(folder), 'firmware_sha256': spec['sha256'],
        'load_address': '0xc0000', 'vectors': vectors,
        'entry_kind': 'decoded AMSS reset; bootloader/BootShell not executed',
    }


def run_u880(profile_id, *, instance=None, key_file=None, limit=100000,
             shadow=False, zero_ram=False, block_trace=False, banks=False,
             nand=False, nand_image=None, lcd=False, live_dir=None, mmc=False,
             synthetic_ssikyu=False, keypad=False, keys_file=None, press=(), irq=False):
    from u880_machine import run
    if limit < 1:
        raise ValueError('Il limite di istruzioni deve essere positivo')
    amss, identity = load_u880(profile_id, instance, key_file)
    if live_dir is not None and not lcd:
        raise ValueError('--live-dir richiede --lcd-bus')
    if lcd:
        live_dir = Path(live_dir) if live_dir is not None else ROOT/'analysis'/profile_id/'frames'
    result = run(amss, limit, shadow=shadow, zero_ram=zero_ram, block_trace=block_trace,
                 banks=banks, nand=nand, nand_image=nand_image, lcd=lcd, live_dir=live_dir, mmc=mmc,
                 fatal_entries=U880_FATAL_ENTRIES.get(profile_id, ()),
                 page_crypto=U880_PAGE_CRYPTO.get(profile_id), synthetic_ssikyu=synthetic_ssikyu,
                 keypad=keypad, keys_file=keys_file, press=press,
                 manager_open_return=U880_MANAGER_OPEN_RETURN.get(profile_id), irq=irq)
    result.update(identity)
    return result
