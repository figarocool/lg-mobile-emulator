"""Package only reviewed emulator files; never recursively include a workspace."""
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DENIED_SUFFIXES={'.pxo','.upx','.bin','.img','.nvm','.nv2','.exe','.elf','.o','.zip'}
DENIED_PARTS={'sdk','firmware','extracted','analysis','data','dumps','instances','references','.git','__pycache__'}
def release_files():
    entries=json.loads((ROOT/'tools/release_files.json').read_text())
    if len(entries)!=len(set(entries)):raise ValueError('Duplicate release entry')
    result=[]
    for name in entries:
        relative=Path(name);path=(ROOT/relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(ROOT) or (ROOT/relative).is_symlink():raise ValueError('Unsafe release path')
        if DENIED_PARTS.intersection(relative.parts) or relative.suffix.lower() in DENIED_SUFFIXES:raise ValueError('Private/binary release entry: '+name)
        if re.search(r'simlock|unlock|z3x|nck',relative.name,re.I):raise ValueError('Excluded tool: '+name)
        if not path.is_file():raise FileNotFoundError(name)
        result.append((name,path))
    return result

def main(output):
    output=Path(output);files=release_files();manifest=[]
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,path in files:
            payload=path.read_bytes();manifest.append(hashlib.sha256(payload).hexdigest()+'  '+name)
            info=zipfile.ZipInfo('lg-mobile-emulator/'+name);info.external_attr=(0o100755 if name=='u310' else 0o100644)<<16
            archive.writestr(info,payload,zipfile.ZIP_DEFLATED)
        archive.writestr('lg-mobile-emulator/MANIFEST.sha256','\n'.join(manifest)+'\n')
    print(f'{output}: {len(files)} reviewed files, {output.stat().st_size} bytes')
if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else ROOT/'lg-mobile-emulator.zip')
