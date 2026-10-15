"""Persistent emulator settings (identity of the emulated handset)."""
import json
import os
from pathlib import Path

PATH = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'u310-emulator' / 'settings.json'
DEFAULTS = {'imei': '356938035643809', 'bt_addr': '00:1B:DC:0F:A3:5E', 'pin': False, 'cpu_mhz': 45.0, 'sim': 'H3G Italia', 'sd_image': '', 'signal': 'Ottimo'}


def load(path=PATH):
    settings = dict(DEFAULTS)
    try:
        settings.update(json.loads(Path(path).read_text()))
    except (OSError, ValueError):
        pass
    return settings


def save(settings, path=PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: settings[k] for k in DEFAULTS if k in settings}, indent=2) + '\n')


def validate(settings):
    """Raise ValueError (message in Italian, shown to the user) when IMEI or Bluetooth address are invalid."""
    import nv_override
    nv_override.normalize_imei(settings['imei'])
    nv_override.parse_bd_addr(settings['bt_addr'])
