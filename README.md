# LG Mobile Emulator

Emulatore sperimentale del telefono **LG U310** (flip UMTS/GSM, 2006, versione H3G Italia V10a).
Non reimplementa il telefono a mano: **esegue il firmware originale** (ARM926) con
[Unicorn](https://www.unicorn-engine.org/) e simula intorno a esso l'hardware: display, tastiera, flash NAND,
SIM, audio, rete radio. Il progetto nasce dal reverse engineering del firmware: ogni componente emulato è stato
ricavato osservando cosa il codice originale si aspetta dall'hardware.

> **Stato: sperimentale.** Il telefono si avvia da zero fino alla schermata iniziale, mostra i due display,
> accetta tutti i tasti (finestra e tastiera del PC) e usa SIM, rete e audio simulati. Non è ancora un emulatore
> completo: vedere "Cosa funziona" e "Cosa manca".

## Licenza e uso

Uso **solo amatoriale e non commerciale**. Vietati l'uso lavorativo/aziendale e l'incorporazione in altri
progetti senza accordo scritto: chi lo incapsula in altri progetti deve riconoscere royalty all'autore.
Testo completo in [`LICENSE`](LICENSE). Autore: **Stefano Basile**, <https://stefanobasile.com/>
(contatti: <https://stefanobasile.com/contatti/>).

Il repository **non contiene il firmware** del telefono (né dump, né flash, né immagini): ogni utente deve
procurarsi i propri file originali.

## Cosa funziona

- **Avvio completo** del firmware originale AMSS (Qualcomm MSM6250) e dei moduli applicativi, fino alla home H3G.
- **Display** principale (176x220) e secondario (96x96), flip aperto/chiuso, tastiera con la disposizione reale.
- **Installazione dai file originali** (`./u310 install`), salvataggio dello stato, ripristino di fabbrica.
- **SIM simulate** con profili: IMSI, ICCID, numero di telefono (EF_MSISDN), nome operatore, PIN/PUK; le scritture
  del telefono (rubrica, SMS) restano nel file della SIM.
- **IMEI e indirizzo Bluetooth** impostabili; il firmware li legge come dalla NV reale.
- **Audio**: toni dei tasti dal protocollo DSP (comando di generazione toni decifrato) e riproduzione dei file
  multimediali tramite i decoder del PC.
- **Rete**: livello radio sostituito da un modello (`netsim`) che risponde al NAS: il telefono si registra su 222-99 (servizio completo),
  mostra "3G", le tacche (livello regolabile dal menu *Rete*) e il nome operatore "H3G".
- **microSD**: immagini FAT con tabella delle partizioni, gestore file nella finestra; il controller MMC/SD del
  telefono è emulato: il driver originale monta la scheda, legge e **scrive** (il telefono crea le cartelle Immagini/Video/Suoni e
  "Aggiungi nuovo" crea cartelle reali nell'immagine).
- **Fotocamera**: sensore OV9655 su I2C emulato; il firmware lo rileva, lo inizializza e avvia l'anteprima (fotogrammi ancora da fare).
- **Finestra GTK** con menu per installare/reinstallare/disinstallare, SIM, microSD e impostazioni.

## Cosa manca

- Lettura di file multimediali dalla microSD e fotocamera che salva foto (da verificare).
- Suono di accensione e suonerie in formato SMAF (`.mmf`).
- Chip Bluetooth (il controller gira sul QDSP, protocollo da ricavare), anteprima e scatto della fotocamera (il sensore OV9655 e il suo
  bus I2C sono emulati e il driver originale parte; manca il DSP della fotocamera), audio fedele via DSP.
- Modem GSM/WCDMA reale (oggi sostituito da un modello a livello NAS).

I dettagli tecnici e il diario del reverse engineering sono in [`docs/BOOT_PROGRESS.md`](docs/BOOT_PROGRESS.md)
e [`docs/ANALISI.md`](docs/ANALISI.md).

## Uso

Requisiti: Python 3, `unicorn`, `capstone`, `numpy` (`python3 -m pip install -r requirements.txt`) e GTK 3 con
PyGObject dal gestore pacchetti. Facoltativi: `dosfstools` e `mtools` (immagini microSD), `ffmpeg`/`fluidsynth` (audio).

Servono i tre file originali V10a H3G (`U310-CODE-…BIN`, `U310-MEDIA-…bin`, `U310-MODULE-…bin`), riconosciuti dal
contenuto (SHA-256).

```bash
./u310 install /percorso/cartella-o-zip-del-firmware   # una volta sola, circa 80 secondi
./u310 run                                              # accende il telefono (finestra)
./u310 reset | uninstall | reinstall <cartella> | info
./u310 sd create|format|info|copy-in|copy-out|ls IMMAGINE
```

Tastiera PC: cifre, `*` `#`, frecce, Invio=OK, Backspace=C, Esc=BACK, F1/F2=softkey, F3=SEND, F4=END, M=MENU.

## Struttura

| Percorso | Contenuto |
| --- | --- |
| `u310`, `tools/u310.py` | avvio da riga di comando |
| `tools/emulator.py` | CPU, memoria, hook e opzioni dell'emulazione |
| `tools/window.py`, `tools/sd_browser.py` | finestra GTK e gestore microSD |
| `tools/provision.py`, `tools/firmware_manifest.py` | installazione dai file originali |
| `tools/usim_card.py`, `tools/sim_profile.py` | SIM/USIM e profili |
| `tools/audio_hle.py`, `tools/qdsp_model.py` | audio e modello del DSP |
| `tools/netsim.py` | rete simulata sotto il NAS |
| `tools/mmc_controller.py`, `tools/mmc_card.py`, `tools/sd_card.py` | controller e schede microSD |
| `tools/test_*.py` | test (`python3 -m unittest discover -s tools -p 'test_*.py'`); alcuni richiedono il firmware installato |

Il resto di `tools/` è strumentazione di analisi usata per ricostruire il comportamento dell'hardware.
