# Installazione Linux e Windows

[English](INSTALLATION.en.md) · [Pagina iniziale](../README.md)

Eseguire i comandi nella cartella del progetto. Python 3.10 o successivo;
Unicorn e bloccato alla versione 2.1.2 per la compatibilita degli snapshot.
Il firmware originale e la chiave locale U880 non sono inclusi.

## Linux: Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip python3-gi python3-gi-cairo gir1.2-gtk-3.0
# Facoltativi per audio e gestione delle immagini microSD:
sudo apt install -y ffmpeg fluidsynth dosfstools mtools
git clone https://github.com/figarocool/lg-mobile-emulator.git
cd lg-mobile-emulator
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -c "import gi, unicorn, capstone, numpy; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; print('Dipendenze OK')"
```

`--system-site-packages` rende disponibile GTK installato da apt. Per gli avvii
successivi basta entrare nella cartella e attivare `.venv`.

## Installare il firmware U310

Fornire CODE, MEDIA e MODULE originali H3G V10a, in una cartella o ZIP.
Il CODE di questa versione e gia in chiaro; non serve una chiave.

```bash
python u310 install "/percorso/firmware-u310.zip"
python u310 run
```

L'installazione costruisce la flash simulata; i file originali non vengono
modificati. `python u310 reset` ripristina la flash U310 di fabbrica, cancellando
le modifiche: non serve per un normale avvio.

## Installare il firmware U880 V10b

Fornire CODE, MEDIA e MODULE corrispondenti alla versione H3G IT dell'8 febbraio
2006. I nomi dei file non contano: vengono controllati i contenuti con SHA-256.
E accettato CODE originale cifrato, CODE gia decifrato con prefisso, oppure AMSS
in chiaro. Le immagini modificate e versioni diverse non sono accettate.

CODE cifrato, con chiave binaria locale di **16 byte** (non un testo esadecimale):

```bash
python u310 install "/percorso/firmware-u880" --profile u880-v10b-h3g --key-file "/percorso/chiave.bin"
```

CODE/AMSS gia decifrato, con gli stessi MEDIA e MODULE:

```bash
python u310 install "/percorso/firmware-u880-in-chiaro" --profile u880-v10b-h3g
```

La chiave non viene estratta da un dispositivo e non viene salvata dall'installatore.
Solo l'immagine decifrata necessaria all'esecuzione resta nei dati locali ignorati
 da Git. Vengono importati e riletti 867 file mediante le API del firmware,
creati metadati di fabbrica sintetici e inizializzato il database UI simulato.
Attendere il messaggio finale; il primo avvio puo richiedere diversi minuti.

```bash
python u310 run --profile u880-v10b-h3g
```

La finestra usa una USIM virtuale senza PIN. Chiudendola normalmente salva lo
stato U880 separato; al successivo avvio lo riprende. Per un avvio dal reset CPU
con la flash installata:

```bash
python tools/u880_window.py --virtual-sim --cold-boot
```

Per la prova senza SIM: `python tools/u880_window.py --without-sim`.
La rete U880 non e ancora simulata: schermata iniziale e menu non implicano
chiamate o registrazione in rete. Vedere [dettagli e limiti](U880.md).

## Windows: WSL2 + WSLg

La finestra usa GTK. Il percorso supportato e Ubuntu in WSL2 con WSLg; **non e
fornito un eseguibile Windows nativo**. Questa procedura non e stata provata su
un PC Windows durante questa pubblicazione.

Occorrono Windows 11 oppure Windows 10 build 19044 o successiva per le app
GUI WSL. Riferimenti Microsoft: [installazione WSL](https://learn.microsoft.com/en-us/windows/wsl/install)
e [app grafiche WSL](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps).

Da PowerShell come amministratore:

```powershell
wsl --install -d Ubuntu
wsl --update
wsl --list --verbose
```

Riavviare se richiesto e completare il primo avvio Ubuntu. La distribuzione deve
usare WSL2; se necessario: `wsl --set-version Ubuntu 2`.

Nel terminale Ubuntu eseguire la sezione Linux, mantenendo il progetto nella
home Linux. I file di Windows sono raggiungibili tramite `/mnt/c`, ad esempio:

```bash
python u310 install "/mnt/c/Users/Mario/Downloads/firmware-u310.zip"
python u310 run
# Oppure U880:
python u310 install "/mnt/c/Users/Mario/Downloads/firmware-u880" --profile u880-v10b-h3g --key-file "/mnt/c/Users/Mario/Downloads/chiave.bin"
python u310 run --profile u880-v10b-h3g
```

La finestra appare sul desktop Windows. Se GTK non trova il display, verificare
WSLg e aggiornamenti Windows/WSL; non assegnare un `DISPLAY` arbitrario.

## Aggiornare e risolvere problemi

```bash
git pull
source .venv/bin/activate
python -m pip install -r requirements.txt
```

- **CODE non riconosciuto:** controllare versione e integrita dei tre file; non rinominare un file di altra versione sperando di renderlo compatibile.
- **Chiave mancante/errata:** serve solo al CODE U880 cifrato. Il risultato viene verificato anche dopo la decifratura.
- **U880 non installato:** eseguire `install --profile u880-v10b-h3g`; `prepare-profile` da solo non costruisce la flash.
- **Snapshot incompatibile:** conservare una copia dei dati; usare Unicorn 2.1.2. Gli snapshot non sono portabili tra versioni diverse di Unicorn.
- **Finestra ferma:** leggere `analysis/window.log` e il report del worker nella cartella temporanea indicata nella riga di comando del processo. Questi file sono locali.
- **Tasti lenti:** il tempo emulato dipende dalle prestazioni del PC; la mappa U880 e ancora sperimentale.

Firmware, chiavi e dati personali non devono essere aggiunti ai commit.
