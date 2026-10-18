"""Known firmware identities used by the multi-handset preparation tools."""
from pathlib import Path
import hashlib


PROFILES = {
    'u310-v10a-h3g': {
        'model': 'LG U310',
        'version': 'V10a H3G',
        'files': {
            'CODE': {
                'name': 'U310-CODE-TRINITYR-V10a-OCT-12-2006-H3G-LATIN_OFF_SEC.BIN',
                'sha256': '1c29d416d47ffa810c92b0099709ceddb77d13e2370037942b754494f5245686',
            },
            'MEDIA': {
                'name': 'U310-MEDIA-V10a-OCT-12-2006-H3G-IT_OFF.bin',
                'sha256': '8ac224756d9ec6f8c757b39fd395c3c3f9a729c6064ee053cfaa19498ccddff7',
            },
            'MODULE': {
                'name': 'U310-MODULE-V10a-OCT-12-2006-H3G-LATIN_OFF_SEC.bin',
                'sha256': '5e9a13c2dd456b39cca0a2554a354b1ae4c656906798c475aa93f7d84643f0f3',
            },
        },
        'bootable': True,
    },
    'u880-v10b-h3g': {
        'model': 'LG U880',
        'version': 'V10b H3G IT',
        'files': {
            'CODE': {
                'name': 'U880-CODE-MUSEDR-V10b-Feb-08-2006-H3G-IT.BIN',
                'sha256': '7229bb63ac76510e0e966dde47dbc32257867082ad78c43ceccc757c6b737140',
            },
            'MEDIA': {
                'name': 'U880-MEDIA-V10b_wm-FEB-08-2006-H3G-IT1.BIN',
                'sha256': '394c99b810909fb25594521675e2484efe7bbf5cc094945537a45f671a06115f',
            },
            'MODULE': {
                'name': 'U880-MODULE-V10b_wm-FEB-08-2006-H3G-none.bin.bin',
                'sha256': '4fffbc57aebf042207226759a387caefa31770e910b5b107a4b3155f44ffe52a',
            },
        },
        # The EFS2 images are understood and the matching AMSS/CODE is now
        # decoded and its AMSS reset runs; full handset startup is still experimental.
        'bootable': False,
        'code_decoder': {'tool': 'tools/decrypt_u880_code.py', 'load_address': 0xc0000, 'file_offset': 0xa00},
        'boot_blocker': 'U880 AMSS reset and diagnostic NAND/LCD run; filesystem layout, hardware events and full handset boot remain unvalidated.',
    },
    'u880-v10a-h3g': {
        'model': 'LG U880',
        'version': 'V10a H3G IT',
        'files': {
            'BOOTLOADER': {
                'name': 'U880-BOOT_LOADER_MUSED.bin',
                'sha256': '8abee5b96fa857216c5bcd2b26b88600c5dc5ce2ce112394b0e6bfe410f5299d',
            },
            'BOOTSHELL': {
                'name': 'U880-bootshell_MUSED.bin',
                'sha256': '9731894f5ea0575644e3854a366167d836c0cab2724e8b127f65bc17b64691a7',
            },
            'CODE': {
                'name': 'U880-CODE-MUSEDR-V10-Oct-27-2005-H3G-IT.bin',
                'sha256': 'd4a21017f6e61d0512a3caec27d041446cf81ad2fc626dfe3017ead8bad03d5a',
            },
            'MEDIA': {
                'name': 'U880-MEDIA-V10a-OCT-27-2005-H3G-IT_OFF.bin',
                'sha256': 'eed72a0b1ef1bce34b59904089583ca8bce128c57bc99b05378cc2938224f125',
            },
            'MODULE': {
                'name': 'U880-MODULE-V10a-OCT-27-2005-H3G-IT.bin',
                'sha256': '880929dcd05ca44fe9a5665a82b0793b1cc8ea7f61948305f8f4311f46c66f84',
            },
        },
        # This complete package is retained for offline startup analysis only.
        # The bootloader fixture rejects the synthetic NAND layout, and CODE
        # has an AMSS runtime, but this profile must not run as U310 firmware.
        'bootable': False,
        'code_decoder': {'tool': 'tools/decrypt_u880_code.py', 'load_address': 0xc0000, 'file_offset': 0xa00},
        'boot_blocker': 'U880 AMSS startup is experimental; validated NAND/BootShell layout and full board startup remain unimplemented.',
    },
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def identify(folder):
    """Identify a complete known set by hashes; return (profile_id, files, problems)."""
    folder = Path(folder)
    candidates = {}
    for path in sorted(folder.rglob('*')):
        if not path.is_file() or path.stat().st_size < 1000:
            continue
        digest = sha256(path)
        for profile_id, profile in PROFILES.items():
            for role, spec in profile['files'].items():
                if digest == spec['sha256']:
                    candidates.setdefault(profile_id, {})[role] = path
    complete = [profile_id for profile_id, found in candidates.items()
                if set(found) == set(PROFILES[profile_id]['files'])]
    if len(complete) == 1:
        profile_id = complete[0]
        return profile_id, candidates[profile_id], []
    if len(complete) > 1:
        return None, {}, ['La cartella contiene più firmware completi; separali prima di preparare un profilo.']
    # Give precise role diagnostics for any partially matching profile.
    problems = []
    for profile_id, profile in PROFILES.items():
        found = candidates.get(profile_id, {})
        if found:
            missing = sorted(set(profile['files']) - set(found))
            problems.append(f"{profile['model']} {profile['version']}: file mancanti: {', '.join(missing)}")
    if not problems:
        problems.append('Firmware non riconosciuto: servono CODE, MEDIA e MODULE di un profilo supportato.')
    return None, {}, problems
