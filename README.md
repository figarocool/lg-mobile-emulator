# LG Mobile Emulator — U310 / U880

[English](README.en.md) · [Installazione Linux e Windows](docs/INSTALLAZIONE.md)

Emulatore sperimentale ARM926 basato su Unicorn: esegue il firmware originale
fornito dall'utente e ne mostra l'interfaccia nella finestra GTK.

| Firmware | Stato |
| --- | --- |
| U310 H3G V10a | Finestra, SIM/rete simulate, tastiera, audio e salvataggio; periferiche ancora parziali |
| U880 H3G IT V10b, 8 febbraio 2006 | Avvio con USIM virtuale fino alla schermata principale; navigazione osservata in Messaggi |
| U880 V10a | Profilo diagnostico sperimentale; non equivale al supporto della finestra V10b |

L'U880 ha display principale/esterno, tastiera e flip simulati, con stato separato
in `data/u880-v10b/`. Rete radio, chiamate e tutte le applicazioni non sono state
validate su U880. La visualizzazione dell'operatore della SIM non prova una
registrazione in rete. Non e un telefono utilizzabile sulla rete reale.

## Licenza e uso

Uso **solo amatoriale e non commerciale**. Vietati l'uso lavorativo/aziendale e l'incorporazione in altri
progetti senza accordo scritto: chi lo incapsula in altri progetti deve riconoscere royalty all'autore.
Testo completo in [`LICENSE`](LICENSE). Autore: **Stefano Basile**, <https://stefanobasile.com/>
(contatti: <https://stefanobasile.com/contatti/>).

Il repository **non contiene il firmware** del telefono (né dump, né flash, né immagini): ogni utente deve
procurarsi i propri file originali.

## Avvio rapido

Installare prima le dipendenze seguendo la [guida Linux/Windows](docs/INSTALLAZIONE.md).
Firmware, chiavi, flash e snapshot non sono distribuiti.

U310, CODE originale in chiaro piu MEDIA e MODULE:

```bash
python u310 install "/cartella/firmware-u310"
python u310 run
```

U880 V10b, CODE cifrato piu MEDIA e MODULE originali:

```bash
python u310 install "/cartella/firmware-u880" --profile u880-v10b-h3g --key-file "/percorso/chiave-locale.bin"
python u310 run --profile u880-v10b-h3g
```

Con CODE U880 gia decifrato (contenitore con prefisso oppure AMSS grezzo), usare
lo stesso comando di installazione **senza `--key-file`**. Il riconoscimento avviene
tramite SHA-256: non accetta automaticamente altre versioni o CODE modificati.
La chiave del CODE cifrato deve essere un file binario locale di 16 byte.
L'installatore non ricava chiavi dal telefono e non modifica il firmware originale.

Durante l'installazione U880 vengono verificati e copiati 867 file mediante
le API filesystem originali nella NAND simulata, poi inizializzato il database UI.
Il primo avvio puo richiedere alcuni minuti. Chiudere normalmente la finestra
per salvare; il successivo avvio riprende lo stato. Per ripartire dal reset CPU
con la flash installata: `python tools/u880_window.py --virtual-sim --cold-boot`.

## Comandi e limiti

Cifre, frecce e Invio funzionano come tastiera del telefono; Esc=BACK,
F1/F2=softkey, F3=SEND, F4=END, M=MENU. La mappa U880 e sperimentale:
alcuni tasti e le singole applicazioni richiedono ancora verifiche.
I tasti brevi vengono mantenuti per il tempo di scansione simulato.

U310 conserva i menu per SIM, microSD e impostazioni; non tutte le periferiche
sono complete. L'U880 usa una USIM sintetica senza PIN e non condivide i file
SIM dell'U310. [Dettagli U880](docs/U880.md).

## Distribuzione

`python tools/make_release.py` produce `lg-mobile-emulator.zip` da una lista
esplicita di file. Contiene codice e documentazione dell'emulatore; nessun
firmware, chiave, snapshot o programma per il telefono.

I documenti storici [ANALISI](docs/ANALISI.md) e [BOOT_PROGRESS](docs/BOOT_PROGRESS.md)
descrivono fasi precedenti del reverse engineering; per lo stato corrente usare
questa pagina e le guide di installazione.
