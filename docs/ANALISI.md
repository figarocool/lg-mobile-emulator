# LG U310: verifica preliminare del firmware

Archivio copiato da `/home/stefano/Scaricati/LG u310 v10a.zip` e decompresso in `firmware/`. I due archivi in Scaricati hanno lo stesso SHA-256.

## Risultati

- Firmware: U310-MSM6250A-V10a-OCT-12-2006-H3G-XX, stringa nel file CODE a offset 0x3cae8.
- Hardware: Qualcomm MSM6250A, CPU ARM926EJ-S; manuale LG, pagina stampata 38. Memoria: 512 Mbit NAND + 512 Mbit SDRAM (64 MiB ciascuna), pagina 41.
- Stringhe AMSS, REX, ZREX e BREW presenti nel CODE: indicano software embedded Qualcomm, non una normale immagine Linux.
- BOOT_LOADER_U310.bin: 7488 byte; primi 8 word compatibili con vettori di salto ARM little-endian. Questo non determina da solo indirizzo di caricamento e mappa memoria.
- MEDIA e MODULE iniziano con EFS2: contenitori da analizzare, non immagini disco standard già identificate.
- CODE non inizia con ELF e non contiene la firma ELF. Il suo inizio ha entropia elevata, ma parti successive contengono stringhe e dati strutturati. Compressione, cifratura e struttura del contenitore NON determinate.
- en_bootshell ha un inizio non riconosciuto; il nome non basta per dimostrare cifratura.
- qemu-system-arm non disponibile nel PATH locale. Nessun avvio effettuato.

## Fattibilità

QEMU standard non offre una macchina LG U310/MSM6250A nelle piattaforme ARM documentate. Selezionare solo una CPU ARM926 o una scheda versatilepb non riproduce il telefono. Non esiste quindi un comando di avvio validato per questi file.

La strada tecnica è riutilizzare la CPU ARM di QEMU aggiungendo un modello della scheda MSM6250A/U310. Prima occorre ricostruire formato CODE, segmenti, indirizzi di caricamento, entry point e layout NAND. Poi implementare RAM/flash, interrupt, timer, clock, watchdog e SBI/PMIC; infine LCD e tastiera. Il DSP/baseband e le attese verso il modem possono richiedere ulteriori modelli o stub. Anche ottenere il menu senza rete è un progetto di reverse engineering e non è garantito dal materiale attuale.

Primo traguardo utile: disassemblare il bootloader con ARM little-endian, identificarne accessi MMIO e mappa memoria; distinguere bootloader di download e normale boot; confrontare il formato del CODE con loader LGMDP. Solo dopo ha senso costruire un harness di esecuzione. Un dump flash da telefono reale potrebbe chiarire dati mancanti.

## Fonti

- Manuale di servizio LG U310: https://www.opweb.de/pdf/lg--u310--service--ID3041.pdf
- QEMU ARM, requisiti del modello di scheda: https://www.qemu.org/docs/master/system/target-arm.html

## SHA-256 dei file estratti

- `BOOT_LOADER_U310.bin` (7488 byte): `3ca6e6bae38a83821e94b8125f64ce273ad145e530c9e15f3c561d3a20187da5`
- `Guida.txt` (394 byte): `d44be2cbf5d9c2bf7319ac38ad37633abc4001e40934e5bb984a665da97b55be`
- `U310-CODE-TRINITYR-V10a-OCT-12-2006-H3G-LATIN_OFF_SEC.BIN` (25172716 byte): `1c29d416d47ffa810c92b0099709ceddb77d13e2370037942b754494f5245686`
- `U310-MEDIA-V10a-OCT-12-2006-H3G-IT_OFF.bin` (8027544 byte): `8ac224756d9ec6f8c757b39fd395c3c3f9a729c6064ee053cfaa19498ccddff7`
- `U310-MODULE-V10a-OCT-12-2006-H3G-LATIN_OFF_SEC.bin` (10108015 byte): `5e9a13c2dd456b39cca0a2554a354b1ae4c656906798c475aa93f7d84643f0f3`
- `en_bootshell_U310R.bin` (179440 byte): `d94a2e0add931e54f41b531b924796e5b761b8f109b2e39142c9642a5508c6d5`
- `u310.nvm` (50540 byte): `ebcc8709b39ac3f851bb4eb8f9efb9f8217c9d8cbb25c59682a8064965f69711`

## Indagine successiva e prototipo

È disponibile `tools/probe_boot.py`, un harness indipendente da QEMU basato su Unicorn e Capstone già disponibili nell’ambiente. Esecuzione: `python3 tools/probe_boot.py`. Il risultato è in `analysis/boot_probe.txt`.

Con base ipotizzata 0xffff0000, il bootloader esegue il salto iniziale, cambia modalità CPU, salva registri e raggiunge PC 0xffff0060. Qui tenta una scrittura di 0xffffffff a 0x84001400 e si ferma intenzionalmente: non è implementata alcuna periferica. La prova verifica solo quel percorso di istruzioni con stato iniziale artificiale, non l’avvio completo e non tutti i dettagli dell’ARM926.

La base è sostenuta dal puntatore Thumb 0xffff02dd: a offset 0x2dc si trova una funzione Thumb coerente, chiamata dal codice ARM a offset 0x178. Un altro riferimento 0xffff0950 punta a codice ARM: non tutti i puntatori sono Thumb.

Altri indirizzi usati nell’inizializzazione: 0x48000000, 0x48000008, 0x600000b0–0x600000cc, 0x84000174–0x84000180, 0x30010000. Le funzioni precise dei registri devono ancora essere identificate. Stack iniziale impostato a 0xffff2800.

Nel CODE, il confine a offset 0x4000 separa un prefisso ad alta entropia da codice ARM leggibile. L’istruzione iniziale è un salto a offset 0x5084, dove compare una funzione coerente. Il puntatore 0x02200040 a offset 0x4044 è compatibile con il blocco a offset 0x4000 caricato a 0x02200000, perché punta alla word a offset 0x4040. È un’ipotesi di caricamento per quel blocco, non ancora una mappa confermata dell’intero file. Il prefisso di 16 KiB non è stato decifrato né identificato.

Disassemblati parziali in `analysis/bootloader.asm`, `analysis/boot_thumb_2dc.asm`, `analysis/boot_arm_950.asm` e `analysis/code_4000.asm`; contengono anche dati che un disassemblatore lineare può interpretare come istruzioni.

Il prossimo passo per un emulatore è identificare i registri sopra elencati e modellarne il comportamento; assegnare semplicemente RAM agli indirizzi hardware non dimostrerebbe un avvio corretto.

## Harness ARM926 esteso

`tools/emulator.py` usa esplicitamente il modello CPU ARM926 di Unicorn. Supporta BOOT e un caricamento sperimentale separato del CODE. Mappa una finestra RAM di 64 MiB ipotizzata; non simula il controller memoria. Default rigoroso: stop su accessi sconosciuti. L'opzione `--shadow-mmio` permette registri di sola memorizzazione, senza semantica hardware.

Risultati verificati:

- BOOT rigoroso: 18 istruzioni, PC 0xffff0060, scrittura non mappata a 0x84001400.
- BOOT diagnostico: 10468 istruzioni, PC 0xffff07ec, lettura non mappata a 0x00019000. La routine effettua accessi a 0x63800000 e dintorni; funzione del controller non ancora confermata.
- CODE rigoroso: 7 istruzioni, scrittura a 0x80003404.
- CODE diagnostico: 31944956 istruzioni, PC 0x2202424, scrittura di 0x112 a 0x6400031c.
- Il ciclo precedente è un azzeramento memoria, non un polling bloccato: routine a 0x02201fb0, destinazione 0x02300000, dimensione 0x0079dc14. Non sono state saltate o patchate istruzioni.

Verifiche eseguite: compilazione Python e asserzioni sui punti di arresto BOOT rigoroso, BOOT diagnostico e CODE rigoroso. Firmware originali non modificati. Inventario, hash, stringhe e mappa entropia riproducibili con `tools/inspect_firmware.py`.

Nessun modello reale di NAND, interrupt, timer, display, keypad o modem è stato implementato. Il programma è un harness per il reverse engineering: l'emulazione completa richiesta resta incompleta. L'identità del blocco CODE iniziale va ancora verificata; le stringhe Update error e JNAND rendono necessario distinguere il codice di aggiornamento dall'avvio del sistema.

## Nuovi componenti ricostruiti

Vedere `analysis/NAND.md` per evidenza disassemblata, limiti e prove.
Implementati sottoinsieme controller NAND e cattura dei due bus LCD.
Decodificati completamente i contenitori EFS2 MEDIA e MODULE: 679 file
originali in `extracted/`, con manifest SHA-256. Aggiunto target AMSS
con rilocazione candidata +0x38000 e vettori a 0x5c000.
La routine di identificazione originale ritorna successo; il percorso
AMSS raggiunge un registro ancora sconosciuto a 0x58c0000c.
Non è stato ottenuto il menu originale.
