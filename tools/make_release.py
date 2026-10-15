"""Build the distributable archive: emulator code and docs only, never firmware, flash images or analysis dumps."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ['u310', 'README.md', 'requirements.txt', 'LICENSE-NOTE.txt']
SKIP_PARTS = {'__pycache__'}


def main(output):
    output = Path(output)
    files = [ROOT / name for name in INCLUDE if (ROOT / name).exists()]
    files += sorted(p for p in (ROOT / 'tools').rglob('*') if p.is_file() and not SKIP_PARTS & set(p.parts)
                    and p.suffix != '.pyc')
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo.from_file(path, f'u310-emulator/{path.relative_to(ROOT).as_posix()}')
            if path.name == 'u310':
                info.external_attr = 0o755 << 16
            archive.writestr(info, path.read_bytes(), zipfile.ZIP_DEFLATED)
    print(f'{output}: {len(files)} file, {output.stat().st_size // 1024} KiB')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'u310-emulator.zip')
