"""SIM profiles: the identity and the persistent contents of each emulated SIM.

A profile is a JSON file in <config>/u310-emulator/sims/<name>.json (identity: IMSI, ICCID, phone number, operator
name, PIN/PUK). Everything the phone writes to the card (phonebook, SMS, preferred networks, ...) is stored next to
it in <name>.state.json, so the SIM keeps its contents between runs and can be moved between emulated phones.
"""
import json
import os
import re
from pathlib import Path

DIR = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'u310-emulator' / 'sims'
DEFAULT_NAME = 'H3G Italia'
DEFAULTS = {'imsi': '222990000000001', 'iccid': '8939990000000000010', 'msisdn': '+393331234567', 'spn': '3',
            'alpha': 'Il mio numero', 'pin': '0000', 'puk': '12345678', 'pin_enabled': False}


def safe_name(name):
    return re.sub(r'[^\w .+-]', '_', name).strip() or DEFAULT_NAME


def path_for(name, directory=None):
    return Path(directory or DIR) / f'{safe_name(name)}.json'


def list_names(directory=None):
    directory = Path(directory or DIR)
    names = sorted(p.stem for p in directory.glob('*.json') if not p.name.endswith('.state.json'))
    return names or [DEFAULT_NAME]


def load(name=DEFAULT_NAME, directory=None):
    profile = dict(DEFAULTS, name=name)
    try:
        profile.update(json.loads(path_for(name, directory).read_text()))
    except (OSError, ValueError):
        pass
    profile['name'] = name
    return profile


def save(profile, directory=None):
    validate(profile)
    path = path_for(profile['name'], directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: profile[k] for k in DEFAULTS}, indent=2) + '\n')
    return path


def state_path(name, directory=None):
    return path_for(name, directory).with_suffix('.state.json')


def validate(profile):
    """Raise ValueError (Italian message) for values a SIM cannot hold."""
    if not re.fullmatch(r'\d{15}', profile['imsi']):
        raise ValueError('IMSI: servono 15 cifre')
    if not re.fullmatch(r'\d{19,20}', profile['iccid']):
        raise ValueError('ICCID: servono 19 o 20 cifre')
    if not re.fullmatch(r'\+?\d{3,20}', profile['msisdn']):
        raise ValueError('Numero di telefono: cifre, con il + iniziale per il formato internazionale')
    if not re.fullmatch(r'\d{4,8}', profile['pin']):
        raise ValueError('PIN: da 4 a 8 cifre')
    if not re.fullmatch(r'\d{8}', profile['puk']):
        raise ValueError('PUK: 8 cifre')
    if len(profile['spn']) > 16 or len(profile['alpha']) > 14:
        raise ValueError('Nome operatore (max 16) o etichetta numero (max 14) troppo lunghi')


def msisdn_record(number, alpha, record_length=28):
    """EF_MSISDN record (TS 31.102 4.2.26): alpha identifier, length, TON/NPI, BCD digits, CCP, extension."""
    alpha_bytes = alpha.encode('latin-1', 'replace')[:record_length - 14].ljust(record_length - 14, b'\xff')
    international = number.startswith('+')
    digits = number.lstrip('+')
    digits += 'f' if len(digits) % 2 else ''
    bcd = bytes(int(digits[i + 1] + digits[i], 16) for i in range(0, len(digits), 2))[:10]
    body = bytes([len(bcd) + 1, 0x91 if international else 0x81]) + bcd.ljust(10, b'\xff') + b'\xff\xff'
    return alpha_bytes + body


def parse_msisdn(record, record_length=28):
    """Inverse of msisdn_record: (number, alpha)."""
    alpha = bytes(record[:record_length - 14]).rstrip(b'\xff').decode('latin-1')
    length = record[record_length - 14]
    if length in (0, 0xff):
        return '', alpha
    ton = record[record_length - 13]
    swapped = record[record_length - 12:record_length - 12 + length - 1]
    digits = ''.join(f'{b & 0xf:x}{b >> 4:x}' for b in swapped).replace('f', '')
    return ('+' if ton & 0x70 == 0x10 else '') + digits, alpha
