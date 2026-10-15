"""Known original firmware files (LG U310 V10a, H3G). The emulator never ships them: every user supplies their own."""
import hashlib
from pathlib import Path

REQUIRED = {
    'CODE': {'sha256': '1c29d416d47ffa810c92b0099709ceddb77d13e2370037942b754494f5245686',
             'name': 'U310-CODE-TRINITYR-V10a-OCT-12-2006-H3G-LATIN_OFF_SEC.BIN', 'pattern': '*CODE*'},
    'MEDIA': {'sha256': '8ac224756d9ec6f8c757b39fd395c3c3f9a729c6064ee053cfaa19498ccddff7',
              'name': 'U310-MEDIA-V10a-OCT-12-2006-H3G-IT_OFF.bin', 'pattern': '*MEDIA*'},
    'MODULE': {'sha256': '5e9a13c2dd456b39cca0a2554a354b1ae4c656906798c475aa93f7d84643f0f3',
               'name': 'U310-MODULE-V10a-OCT-12-2006-H3G-LATIN_OFF_SEC.bin', 'pattern': '*MODULE*'},
}
OPTIONAL = {
    'BOOT': {'sha256': '3ca6e6bae38a83821e94b8125f64ce273ad145e530c9e15f3c561d3a20187da5', 'name': 'BOOT_LOADER_U310.bin'},
    'BOOTSHELL': {'sha256': 'd94a2e0add931e54f41b531b924796e5b761b8f109b2e39142c9642a5508c6d5', 'name': 'en_bootshell_U310R.bin'},
    'NVM': {'sha256': 'ebcc8709b39ac3f851bb4eb8f9efb9f8217c9d8cbb25c59682a8064965f69711', 'name': 'u310.nvm'},
}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def find(folder):
    """Match the files in a folder by content hash (file names do not matter). Returns (found, problems)."""
    wanted = {**{k: v['sha256'] for k, v in REQUIRED.items()}, **{k: v['sha256'] for k, v in OPTIONAL.items()}}
    found, problems = {}, []
    for path in sorted(Path(folder).rglob('*')):
        if path.is_file() and path.stat().st_size > 1000:
            digest = sha256(path)
            for role, expected in wanted.items():
                if digest == expected:
                    found.setdefault(role, path)
    for role in REQUIRED:
        if role not in found:
            candidates = [p.name for p in Path(folder).rglob(REQUIRED[role]['pattern']) if p.is_file()]
            hint = f' (trovati con nome simile ma contenuto diverso: {", ".join(candidates)})' if candidates else ''
            problems.append(f'Manca il file {role} originale V10a H3G ({REQUIRED[role]["name"]}){hint}')
    return found, problems
