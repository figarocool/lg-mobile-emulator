# Linux and Windows installation

[Italiano](INSTALLAZIONE.md) · [Home](../README.en.md)

Run commands from the project directory. Use Python 3.10 or newer. Unicorn is
pinned to 2.1.2 for snapshot compatibility. Original firmware and the local
U880 key are not included.

## Linux: Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip python3-gi python3-gi-cairo gir1.2-gtk-3.0
# Optional audio decoders and microSD image utilities:
sudo apt install -y ffmpeg fluidsynth dosfstools mtools
git clone https://github.com/figarocool/lg-mobile-emulator.git
cd lg-mobile-emulator
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -c "import gi, unicorn, capstone, numpy; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; print('Dependencies OK')"
```

`--system-site-packages` exposes the GTK packages installed through apt. On
later launches, enter the project directory and activate `.venv`.

## Install U310 firmware

Supply original H3G V10a CODE, MEDIA and MODULE in a directory or ZIP.
This version's CODE is unencrypted; no key is needed.

```bash
python u310 install "/path/to/u310-firmware.zip"
python u310 run
```

Installation builds simulated flash without changing the original files.
`python u310 reset` restores U310 factory flash and discards local changes;
it is not needed for a normal launch.

## Install U880 V10b firmware

Supply matching original CODE, MEDIA and MODULE for H3G IT, February 8, 2006.
Files are identified by SHA-256, not their names. Accepted CODE inputs are the
original encrypted image, decoded CODE including its prefix, or raw plaintext
AMSS. Modified images and other firmware versions are rejected.

Encrypted CODE requires a local **16-byte binary key file**, not hexadecimal text:

```bash
python u310 install "/path/to/u880-firmware" --profile u880-v10b-h3g --key-file "/path/to/key.bin"
```

For already decrypted CODE/AMSS, with matching MEDIA and MODULE:

```bash
python u310 install "/path/to/plain-u880-firmware" --profile u880-v10b-h3g
```

The installer does not obtain a key from a handset and does not save the key.
The decoded runtime image is stored only in local Git-ignored application
data. Installation imports and reads back 867 files using original firmware
APIs, creates synthetic factory metadata, and initializes the simulated UI
database. Wait for the completion message; first installation and boot may
take several minutes.

```bash
python u310 run --profile u880-v10b-h3g
```

The window uses a virtual USIM without a PIN. Close it normally to save its
separate U880 state; the next launch resumes it. For a CPU reset with installed
flash:

```bash
python tools/u880_window.py --virtual-sim --cold-boot
```

To run without a SIM: `python tools/u880_window.py --without-sim`.
U880 radio is not simulated yet: a home screen or menu does not mean network
registration or calling works. See [U880 details](U880.en.md).

## Windows: WSL2 + WSLg

The GTK window runs through Ubuntu on WSL2/WSLg. **No native Windows executable
is provided.** These Windows steps were not tested on a Windows PC during
this release.

GUI apps require Windows 11 or Windows 10 build 19044+. Microsoft references:
[install WSL](https://learn.microsoft.com/en-us/windows/wsl/install) and
[WSL GUI apps](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps).

In an administrator PowerShell:

```powershell
wsl --install -d Ubuntu
wsl --update
wsl --list --verbose
```

Reboot if requested and complete Ubuntu's first-run setup. Ubuntu must use
WSL2; if necessary, run `wsl --set-version Ubuntu 2`.

Inside Ubuntu, follow the Linux section and keep the project in your Linux
home directory. Access Windows files through `/mnt/c`, for example:

```bash
python u310 install "/mnt/c/Users/Alex/Downloads/u310-firmware.zip"
python u310 run
# Alternatively, U880:
python u310 install "/mnt/c/Users/Alex/Downloads/u880-firmware" --profile u880-v10b-h3g --key-file "/mnt/c/Users/Alex/Downloads/key.bin"
python u310 run --profile u880-v10b-h3g
```

The window should appear on the Windows desktop. If GTK cannot find a display,
check WSLg and Windows/WSL updates; do not assign an arbitrary `DISPLAY` value.

## Updating and troubleshooting

```bash
git pull
source .venv/bin/activate
python -m pip install -r requirements.txt
```

- **Unknown CODE:** check all three files and their firmware version; renaming a different image cannot make it compatible.
- **Missing/wrong key:** a key is needed only for encrypted U880 CODE. Decoded results are verified too.
- **U880 not installed:** use `install --profile u880-v10b-h3g`; `prepare-profile` alone does not build the flash.
- **Incompatible snapshot:** back up local data and use Unicorn 2.1.2. Snapshots are not portable across Unicorn versions.
- **Stopped window:** inspect `analysis/window.log` and the worker report in its temporary directory, shown in the process command line. These files stay local.
- **Slow keys:** emulated time depends on PC performance; U880 mapping remains experimental.

Do not commit firmware, keys or personal data.
