"""Install U880 V10b from user-owned files into an isolated simulated phone."""
import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path
from firmware_profiles import PROFILES
from extract_efs import parse
from native_fs_calls import NativeFsCalls
from u880_machine import run
from u880_ui_fixture import UiNormalBootFixture
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/u880-v10b'
AMSS_SHA='95dfa53aee43bd97aba158878e655adeb0d9b3fc0f02c13efb30319c0a29f9d0'
API=dict(open=0xbd2c81,close=0xbd2ce3,read=0xbd2d21,write=0xbd2d6b,test=0xbd3359,mkdir=0xbd32d1)
def digest(data):return hashlib.sha256(data).hexdigest()
def decode_code(data,key=None):
    """Accept verified raw AMSS, decoded CODE with prefix, or original encrypted CODE."""
    from decrypt_u880_code import PREFIX,decrypt,validate_vectors
    if digest(data)==AMSS_SHA:
        validate_vectors(bytes(PREFIX)+data)
        return data,'plain-amss'
    if len(data)>PREFIX and digest(data[PREFIX:])==AMSS_SHA:
        validate_vectors(data)
        return data[PREFIX:],'plain-code'
    if digest(data)!=PROFILES['u880-v10b-h3g']['files']['CODE']['sha256']:
        raise ValueError('CODE non riconosciuto / Unknown CODE: only the original U880 V10b is supported')
    if key is None:raise ValueError('CODE cifrato: specificare --key-file / Encrypted CODE: supply --key-file')
    plain=decrypt(data,key);validate_vectors(plain)
    if digest(plain[PREFIX:])!=AMSS_SHA:raise ValueError('Chiave o CODE errato / Wrong key or CODE')
    return plain[PREFIX:],'encrypted-code'
def requests(files,progress):
    def check(result,action):
        if result['status']:raise RuntimeError(f'{action}: FS {result["status"]}')
    directories=sorted({str(parent) for path,_ in files for parent in Path(path).parents if str(parent)!='.'},key=lambda s:(s.count('/'),s))
    for path in directories:
        result=yield dict(operation='test',path=path,kind=0);check(result,path)
        if not result['present']:
            result=yield dict(operation='mkdir',path=path);check(result,path)
    for index,(path,data) in enumerate(files,1):
        result=yield dict(operation='create',path=path);check(result,path);handle=result['handle']
        result=yield dict(operation='write',handle=handle,data=data);check(result,path)
        if result['count']!=len(data):raise RuntimeError('Short write: '+path)
        result=yield dict(operation='close',handle=handle);check(result,path)
        result=yield dict(operation='open',path=path);check(result,path);handle=result['handle']
        result=yield dict(operation='read',handle=handle,length=len(data));check(result,path)
        if result['count']!=len(data) or result['sha256']!=digest(data):raise RuntimeError('Readback mismatch: '+path)
        result=yield dict(operation='close',handle=handle);check(result,path)
        if index%25==0 or index==len(files):progress(f'{index}/{len(files)} files verified',flush=True)
def checked(report):
    if report.get('unicorn_error') or 'fatal' in report.get('stop','').lower():
        raise RuntimeError('U880 initialization stopped: '+report['stop'])
def install(source,key_file=None):
    source=Path(source);key=Path(key_file).read_bytes() if key_file else None
    DATA.mkdir(parents=True,exist_ok=True)
    if (DATA/'resources.zip').exists():raise ValueError('U880 gia installato / Already installed: data/u880-v10b/resources.zip')
    with tempfile.TemporaryDirectory(prefix='u880-install-') as tmp:
        tmp=Path(tmp)
        if source.is_file() and zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as z:
                for name in z.namelist():
                    target=(tmp/'input'/name).resolve()
                    if not target.is_relative_to((tmp/'input').resolve()):raise ValueError('Unsafe ZIP path')
                z.extractall(tmp/'input')
            source=tmp/'input'
        if not source.is_dir():raise ValueError('Indicare cartella o ZIP / Supply a directory or ZIP')
        found={};code_candidates=[];spec=PROFILES['u880-v10b-h3g']['files']
        for path in source.rglob('*'):
            if not path.is_file():continue
            data=path.read_bytes();sha=digest(data)
            for role in ('MEDIA','MODULE'):
                if sha==spec[role]['sha256']:found[role]=data
            if sha==spec['CODE']['sha256'] or sha==AMSS_SHA or (len(data)>0xa00 and digest(data[0xa00:])==AMSS_SHA):code_candidates.append(data)
        if not code_candidates or set(found)!={'MEDIA','MODULE'}:raise ValueError('Servono CODE, MEDIA e MODULE originali U880 V10b / Missing matching U880 V10b files')
        code,encoding=decode_code(code_candidates[0],key)
        files=[('LGAPP/Pxo/'+Path(name).name,data) for name,data,_ in parse(found['MODULE']) if data is not None]
        files.extend((name.lstrip('/'),data) for name,data,_ in parse(found['MEDIA']) if data is not None)
        flex=next(data for name,data in files if name=='LGAPP/Media/Flex/Flex.ini')
        country=int(re.search(rb'^FLEX_COUNTRY_CODE=(\d+)\s*$',flex,re.M).group(1))
        session=NativeFsCalls(requests(files,print),api=API,current_tcb=0x1c3ded4)
        config=dict(shadow=True,zero_ram=True,block_trace=True,banks=True,nand=True,lcd=True,mmc=True,irq=True,keypad=True,synthetic_ssikyu=True,page_crypto=(0xdcdf8,0xdce36),synthetic_country=country,dynamic_code=True,fast=True,fatal_entries=(0xbd1692,0xbd1490))
        print('U880: installazione dei file / Installing firmware resources',flush=True)
        imported=DATA/'import-stage.zip'
        if not imported.exists():
            report=run(code,2000000000,debug_at=0xcc4e0,debug_session=session,debug_continue=True,fast_import=True,post_import_limit=1,save_checkpoint=imported,**config)
            checked(report)
            if not report.get('native_fs_import_complete'):raise RuntimeError('Native file import incomplete')
            print('Import checkpoint PC: '+report['pc'],flush=True)
        else:
            print('Riprendo importazione verificata / Resuming verified file import',flush=True)
        print('U880: inizializzazione interfaccia / Initializing UI',flush=True)
        pending=DATA/'resources.pending.zip'
        fixture=UiNormalBootFixture()
        ui_report=run(code,2000000000,resume=imported,debug_at=0xcc6da,debug_session=fixture,debug_on_resume=True,debug_continue=True,post_import_limit=100000,save_checkpoint=pending,**config)
        checked(ui_report)
        if fixture.calls!=3:raise RuntimeError('UI initialization incomplete')
        (DATA/'amss.bin').write_bytes(code)
        pending.replace(DATA/'resources.zip')
        imported.unlink(missing_ok=True)
        (DATA/'install.json').write_text(json.dumps(dict(model='U880',version='V10b',encoding=encoding,amss_sha256=digest(code),files_verified=len(files),synthetic_factory_metadata=True,firmware_modified=False),indent=2)+'\n')
    print('Installazione completata / Installed. python u310 run --profile u880-v10b-h3g',flush=True)
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--key-file',type=Path);a=p.parse_args()
    install(a.source,a.key_file)
