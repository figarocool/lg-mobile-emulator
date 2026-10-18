# LG Mobile Emulator — U310 / U880

[Italiano](README.md) · [Linux and Windows setup](docs/INSTALLATION.en.md)

Experimental ARM926/Unicorn emulator running user-supplied original firmware
inside a GTK phone window.

| Firmware | Status |
| --- | --- |
| U310 H3G V10a | Window, simulated SIM/network, keypad, audio and persistence; peripherals remain partial |
| U880 H3G IT V10b, February 8, 2006 | Boots with a virtual USIM to the original home screen; Messages navigation observed |
| U880 V10a | Experimental diagnostic profile, not equivalent to the V10b window support |

U880 has main/external displays, keypad and flip inputs, with separate state
under `data/u880-v10b/`. U880 radio registration, calls and every application
have not been validated. A displayed SIM operator name does not demonstrate
network registration. This does not connect to real cellular networks.

## License

**Hobby and non-commercial use only.** Commercial/business use and incorporation
into other projects require a written agreement; the author's royalty terms
apply. Read [LICENSE](LICENSE) for the full, authoritative terms.
Author: **Stefano Basile**, [website](https://stefanobasile.com/),
[contact](https://stefanobasile.com/contatti/).

No firmware, keys, phone dumps or flash images are distributed.

## Quick start

Install dependencies using the [Linux/Windows guide](docs/INSTALLATION.en.md).

U310, original unencrypted CODE plus MEDIA and MODULE:

```bash
python u310 install "/path/to/u310-firmware"
python u310 run
```

U880 V10b, original encrypted CODE plus matching MEDIA and MODULE:

```bash
python u310 install "/path/to/u880-firmware" --profile u880-v10b-h3g --key-file "/path/to/local-key.bin"
python u310 run --profile u880-v10b-h3g
```

For already decrypted U880 CODE (with its prefix or raw AMSS), omit
`--key-file`. SHA-256 identifies supported images; other firmware versions or
modified CODE are not accepted automatically. Encrypted CODE requires the
user's own 16-byte binary key file. The installer does not obtain keys from a
handset or patch the original firmware.

U880 installation copies and verifies 867 files using the original filesystem
APIs in simulated NAND, then initializes the UI database. Initial installation
and boot can take several minutes. Close the window normally to save; later
launches resume the saved state. For a CPU reset using the installed flash:
`python tools/u880_window.py --virtual-sim --cold-boot`.

## Controls and limitations

Digits, arrows and Enter control the phone; Esc=BACK, F1/F2=softkeys,
F3=SEND, F4=END and M=MENU. U880 mapping is experimental; individual keys and
applications still need verification. Short key presses are held for a
minimum simulated scan interval.

U310 retains SIM, microSD and settings menus; peripheral support is partial.
U880 uses a synthetic USIM without a PIN and does not share U310 SIM files.
See [U880 details](docs/U880.en.md).

## Distribution

`python tools/make_release.py` builds `lg-mobile-emulator.zip` from an explicit
file list. It includes emulator code and documentation, without firmware,
keys, snapshots or handset programs.

Historical [analysis](docs/ANALISI.md) and [boot notes](docs/BOOT_PROGRESS.md)
cover earlier reverse-engineering stages. Use this README and setup guides
for current behavior.
