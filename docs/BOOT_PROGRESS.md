# Stato dell'emulazione LG U310

Il menu normale non è ancora stato ottenuto. Sono eseguite istruzioni originali
del firmware; nessuna routine di avvio è stata saltata o modificata.
Gli accessi hardware non completamente ricostruiti usano modelli esplicitamente
sperimentali e registri shadow.

## Risultati verificati

- Loader CODE: immagine originale “Software Update”.
- Percorso AMSS: inizializzazione RAM, configurazione MMU, discovery NAND,
  scheduler REX e creazione di 67 task.
- Il loop a `0x012662FC` è il task idle, identificato dalla struttura
  `REX Idle Tas` a `0x019A4104`, non un fatal error.
- IRQ0 attraversa il vettore candidato a `0x0005C018`, l'handler ARM
  `0x01683148`, il dispatcher `0x00D1217A` e il callback timer `0x00156D34`.
  I timer REX scadono attraverso codice originale e sbloccano i task.
- Il bus LCD emette la schermata originale “File System Startup. Please Wait”.
  L'immagine è ricostruita dai pixel emessi dal firmware, non da testo aggiunto.

## Componenti implementati in questo passaggio

### Timer e IRQ

Il firmware registra IRQ0 con handler `0x00156D35`. Il conteggio timer è scritto
a `0x80003450` (inizialmente 164). Il callback pulisce IRQ0 scrivendo 1 in
`0x84000248`. Il dispatcher legge il numero di interrupt in `0x840002B0` e
`0x840002C0`: il valore `0x3F` significa nessuna sorgente disponibile.
La maschera bassa è a `0x84000250`.

Il modello assume clock da 32.768 kHz, CPU nominale da 180 MHz e un ciclo
per istruzione. Durante il loop idle avanza al prossimo evento; non modifica
i segnali REX direttamente. La rilocazione dei vettori a `0x5C000` resta
un'ipotesi, perché il bootstrap completo e il suo mapping ROM non sono noti.
Sono gestiti soltanto IRQ0 e il relativo ACK, senza FIQ, USB, DSP o altri IRQ.

### Registri osservati

Le pagine `0x58C00000`, `0x50C00000`, `0x65800000` e `0x65000000` conservano
i valori scritti, senza la semantica completa dei controller. Le ultime due
sono associate al percorso USB: `0x01453160` fa riferimento a `usbdc.c` e
`0x0162BB1C` imposta l'handler dell'interrupt `0x1D`.

### Clock MMC

`0x010F0E78` scrive 1 a `0x61800000`, poi attende bit 8 di `0x61800004`.
Il messaggio d'errore è `mmc_stop_clock() failed`. La routine di start scrive
2 a `0x61800000`. Il modello conserva lo stato avviato/arrestato del clock;
non fornisce una scheda SD, risposte ai comandi MMC o interrupt di trasferimento.
Un test esegue la routine originale di stop fino al ritorno con R0=1.

### NAND spare e porta diretta

È aggiunta la conservazione di 16 byte spare per pagina, oltre ai 512 byte dati:
read/program/erase e checkpoint mantengono entrambe le aree. Lo spare iniziale
è cancellato; non è un dump fisico del telefono. Non è calcolato ECC hardware.

La routine `0x00358A1C` legge una pagina, modifica il controllo EBI a
`0x600000E0`, invia il byte `0x74` alla porta diretta `0x28000000`, legge una
halfword e interpreta i due bit bassi. Il modello permette questo controllo
di stato, assumendo assenza di errori fisici ECC; non emula tutti i comandi
della porta NAND diretta.

### GRAM LCD

La routine di trasferimento del loader mostra: R21 = cursore (Y alto, X basso),
R44 = finestra X (fine alto, inizio basso), R45 = finestra Y, R22 = pixel.
Il modello ricostruisce una GRAM 176×220 e la esporta come RGB565. La schermata
AMSS leggibile con il testo di startup conferma la coerenza di questo percorso,
ma ID, stato, alimentazione, orientamenti alternativi e pannello secondario
non sono emulati completamente. Il readback dei registri resta diagnostico.

## Checkpoint e riproduzione

`tools/checkpoint.py` salva CPU (compresi registri bancati e CP15), memoria,
NAND, spare, stato timer, clock MMC e pixel LCD. Usa ZIP con JSON e byte grezzi,
senza pickle. Il restore controlla versione Unicorn, configurazione, hash CODE
e dimensioni. È possibile aggiungere i modelli timer e MMC a checkpoint che
non li avevano; disattivarli dopo averli usati viene rifiutato.

`amss_checkpoint2.zip` si trova nell'idle REX prima degli interrupt.
`amss_display_checkpoint.zip` contiene la prima schermata AMSS.
I checkpoint successivi comprendono anche il lavoro sulla flash simulata;
non sono dump di un telefono reale. I checkpoint vecchi senza spare/GRAM non
possono ricostruire byte che il vecchio modello non aveva conservato.

Per il report, `instructions` conta gli hook visitati, compreso quello di una
istruzione che può fermarsi o fallire. Con `--block-trace` è invece una stima
per blocchi (anche il tempo IRQ è stimato). Le istruzioni guest sono sempre
eseguite da Unicorn: non vengono sostituite da memcpy/memset host.

## Parti ancora mancanti

Il filesystem lavora inizialmente su una flash sintetica vuota. MEDIA, MODULE
e NVM non sono ancora installati nel filesystem NAND originale. I 679 file
estratti esistono sul computer, ma questo non li rende accessibili al guest.
Restano inoltre le semantiche complete dei controller, altri interrupt,
PMIC/SBI, DSP/baseband, input e caricamento PXO4. Non è dimostrata l'emulazione
completa del firmware o il funzionamento del menu, audio, telefonia e USB.

## NV e metadati SSIKYU

Il debugger ferma AMSS sul fatal entry `0x0161E028`, conservando gli argomenti.
La flash vuota raggiunge `nvimnv.c`, riga candidata 2079, con il messaggio
`Failed SSIKYU initialization`. Le istruzioni non sono patchate per ignorarlo.

La funzione di inizializzazione SSIKYU è `0x0006F9AC`; passa per `0x000707F2`
e `0x00070C96`. Seleziona i primi tre blocchi buoni nell'intervallo 25–30
(nel modello: 25, 26, 27) e controlla intestazioni cifrate con versione 1.
Le routine `0x000706F4` e `0x00070732` decifrano/cifrano pagine di 512 byte.
Sono state eseguite isolatamente e il round-trip è verificato, con cifrato
diverso dal plaintext. La scansione dei candidati allineati a 512 byte in
CODE, en_bootshell e u310.nvm non ha trovato le prime due intestazioni.
Non è una prova che non possano esistere dati equivalenti in altri formati.

`--synthetic-ssikyu` è una prova separata: costruisce sette pagine vuote,
con magic/version ricavati dai fallback del firmware, e le cifra eseguendo
la routine originale. Le inserisce nel blocco 27 solo se la NAND è sintetica
e le pagine sono cancellate. Non modifica il firmware o il backup NV.
Ripartendo prima della lettura, SSIKYU imposta il proprio flag a 1 e AMSS
prosegue. Questo non ricostruisce identità, calibrazione o chiavi del telefono.

Un checkpoint nel mezzo di una lettura NAND contiene già il vecchio buffer;
inizializzare lo storage dopo quella lettura non corregge il buffer in corso.
La prova positiva è ripartita dal checkpoint precedente al read.

## Memorie DSP

Il task QDSP copia halfword a `0x58000000` e `0x58200000`; carica word a
`0x58400000` e `0x58800000`. MDSP scrive anche a `0x50000000` e finestre
analoghe. Il modello mappa otto finestre dati da 256 KiB, senza permesso
di esecuzione ARM. Conservare il microcodice non equivale a eseguirlo:
non è presente un emulatore della ISA dei DSP né una completa risposta ai mailbox.
L'ultima prova con metadati sintetici resta nel servizio MDSP, con segnale 8
pendente. Il task UI attende ancora il segnale di startup `0x40000000`.

### Esperimento successivo: protocollo di gestione MDSP

La routine `0x482b12` scrive la maschera richiesta a `0x5040b380`, il comando
1 a `0x50206310` e il doorbell a `0x50c00008`. Il completamento controllato
da `0x48288c` richiede comando zero e risposta a `0x5040b37c` uguale alla
maschera conservata a `0x019a3980`. La tabella a `0x568c08` seleziona indice
1: il callback registrato su IRQ5 (`0x482590`) entra in `0x4828d0` e quindi
nel gestore di completamento. IRQ4 ha indice 0 e non è il completamento
di questo comando; la prima prova su IRQ4 non sbloccava il gestore corretto.

`tools/mdsp_management.py`, attivato solo da `--mdsp-management`, implementa
questa risposta a livello alto. L'attivazione riuscita è un'assunzione HLE,
non una verifica dell'esecuzione del modulo DSP. I comandi sconosciuti non
sono confermati. Non vengono patchati codice ARM, TCB o segnali REX.
Il modello interrupt conserva separatamente i pending delle sorgenti 1–31,
rispetta la maschera e cancella solo i bit ACK; priorità hardware e banco
alto restano incompleti. I checkpoint conservano i nuovi pending.

La prova da `amss_latest.zip` esegue altri 5 milioni di istruzioni stimate,
completa 318 richieste e poi altri 5 milioni ne completano 317. Il segnale 8
non resta permanentemente pendente, ma MDSP continua a caricare moduli,
la UI attende ancora `0x40000000` e il display resta sulla schermata di
startup del filesystem. Nessun fatal intercettato in queste due prove.
Questa sequenza non dimostra un avvio riuscito né un DSP funzionante.
Checkpoint della seconda prova: `amss_management_latest.zip`.

Un test esegue direttamente la routine originale `0x48288c`: un comando
non completato o una risposta diversa non raggiungono REX; comando zero
con maschera corrispondente raggiunge la prima chiamata REX prevista.
Il test si ferma prima degli effetti della chiamata, senza sostituire codice.

## Avanzamento successivo: DSP boot-ready e matrice tastiera

Un breakpoint di sola osservazione a `0x482714` identifica il recupero
chiamato da `0x48285c`. Dopo la sequenza di controllo `0x1b`, `0x3b` a
`0x50c00010` e la copia del programma, `0x482848` legge la halfword
`0x5020625a`: zero entra nel recupero. La risposta HLE di avvio restituisce
1 alla prima lettura dopo quella sequenza. È un'assunzione di DSP avviato,
non esecuzione della sua ISA; resta disattivata senza `--mdsp-management`.
Con questa risposta e due conferme del comando 1, MDSP passa ad attendere
`0x601f`; UI riceve `0x40000000` ed esegue il proprio codice. L'esperimento
precedente privo di boot-ready ricaricava continuamente i moduli.

La prima nuova schermata è “G a n g I m a g e M o d e”, stringa a `0x686f8`.
Il ramo è scelto dalla funzione `0x1444042`: legge cinque righe active-low
a `0x48000070` e pilota sette colonne con la tabella a `0x14b9b78`, usando
gli output `0x48000000` e `0x84000150`. La memoria diagnostica zero faceva
risultare premuti i quattro incroci (1,0), (3,0), (1,2), (3,2), con coordinate
da zero. `tools/keypad.py` rende le righe inattive alte e modella la selezione
delle colonne, conservando gli altri bit GPIO. Due prove eseguono la routine
originale senza patch: nessun tasto restituisce 0; i quattro incroci
restituiscono 1. Etichette dei tasti, debounce e interrupt restano mancanti.

Con `--keypad` l'avvio originale evita Gang Image e raggiunge l'apertura
`LGAPP/Pxo/PhoneMngr.pxo` (`0x68614`). Il breakpoint a `0x68622` osserva
R0=`0xffffffff`, errore di apertura. Il file originale è estratto da MODULE
in `extracted/MODULE/UPLOAD/Pxo/PhoneMngr.pxo`; non è presente nella NAND
sintetica. Il normale startup non è ancora dimostrato. Il task FS Compat
continua operazioni native e il display conserva “File System Startup”.

Riproduzione: comando README con HLE, keypad e `amss_latest.zip`, limite
10 milioni. Report `amss_shadow_nand_lcd_banks_irq_mmc_blocks_mdsp_hle_keypad.json`,
checkpoint `amss_startup_diagnosed.zip`, watch: combinazione di servizio=0,
apertura PhoneMngr=-1. Nessun fatal intercettato in questa prova.
I nuovi checkpoint conservano doorbell, reset/release, boot pending, contatori
MDSP e matrice premuta, oltre alla memoria e agli interrupt. La finestra usa
ora anche il modello tastiera. Verifica complessiva: 32 test passano.

## Backup U880/U890 fornito successivamente (dettagli)

È copiata la sorgente `NV_U880_U890.nv2` in `references/`. Il suo header indica
U890, versione contenitore 2, 417 record. La trasformazione reversibile trovata
è `(cipher - key) XOR key`, con una chiave periodica di 16 byte; header,
conteggio, timestamp e re-encoding sono coerenti con il file originale.

I record sono di 133 byte: byte iniziale 1, ID uint16, 128 byte payload,
status uint16. Il backup U310 ha 380 ID distinti (379 status 0, uno status 5).
Il donor ha 417 record e 408 ID distinti: nove ID sono ripetuti e vengono
conservati. Fra i due ci sono 349 ID comuni; 156 gruppi payload coincidono
e 193 differiscono. Il donor è utile per verificare il formato, ma non è
stato sostituito agli NV U310. Non contiene direttamente le intestazioni
SSIKYU raw richieste al boot; i backup sono record logici da ripristinare.

## Importazione risorse e controllo Flex superato

Importati 129 MODULE e 550 MEDIA con create/write/close/open/read originali:
679 hash di rilettura corrispondono alle sorgenti. Il nuovo riavvio trova
PhoneMngr.pxo e raggiunge 0x6877c (prosecuzione normale) a 200 milioni
di istruzioni stimate. Il parametro paese mancante è un header opzionale
SSIKYU del blocco 25 pagina 0, costruito nella sola NAND sintetica dal Flex.ini.
La API NV originale conferma item 9025 status=0 e valore uint16=1:
vedere native_country_verified.json. Nessuna istruzione firmware modificata.
Il backup NV originale non è stato ripristinato.

A 300 milioni UI attende ancora FS Compat; lo stack mostra la richiesta
RecMngr.bin da 0x300000 byte. L'esecuzione prosegue nella scansione/allocazione
nativa della flash; questa fase non prova ancora il caricamento del menu.
Aggiunti breakpoint di sola osservazione fra 0x68784 e 0x68824 per distinguere
completamento dei controlli, timer e lancio servizi. 34 test passano, inclusa
esecuzione del lettore SSIKYU originale con header validi e invalidi.

A 400 milioni di istruzioni stimate il task UI è nuovamente corrente, con
wait_signals=0: l'attesa del filesystem è terminata. PC 0x00d87fda scorre
le righe della configurazione originale Flex/NVDB. Il display conserva ancora
il frammento diagnostico; non si deve interpretare il task attivo come menu
avviato. Checkpoint amss_resources_next2.zip e report omonimo JSON.

Traccia di cinque milioni di istruzioni dal checkpoint next3:
18 aperture, 14 scritture, 7 richieste NV e 4 letture. Le letture sono del
Flex.ini originale (89435 byte); le scritture riguardano RecMngr.bin, in
record da 6/8/16/24 byte. Non si osserva un singolo loop bloccato: il firmware
sta inizializzando le impostazioni. La traccia `native_api_watch.py` registra
solo operazioni, nomi file, lunghezze e ID NV; non il contenuto dei payload.

Il timer evita i round trip Unicorn quando non ci sono interrupt pendenti.
Replay di un milione di istruzioni dal checkpoint next4, confrontato con
il codice precedente: stessi registri, hash dell'intera RAM, stato timer
e attività NAND (timer_optimization_replay.json). Tutti i 34 test passano.
La finestra accetta ora `--resume percorso.zip` e seleziona i checkpoint
con risorse importate come predefiniti.

## Esecuzione PXO originale confermata

Replay dal checkpoint next6 per 100 milioni di istruzioni stimate: 5242
blocchi eseguiti in RAM oltre il CODE residente. L'indirizzo 0x032b4380
è il callback PhoneMngr registrato, ed è stato effettivamente eseguito.
Durante il replay, chiamanti in RAM lanciano IdleMngr, PwrOn e UsimMngr.
Questo supera la precedente sola verifica di presenza/handle del loader.
Il checkpoint amss_pxo_dispatch.zip contiene sei moduli registrati:
AlwaysOnPDPMngr, DataCallManager, PhoneMngr, IdleMngr, PwrOn, UsimMngr.
Non prova ancora il menu o il funzionamento completo degli applicativi.

La sonda di lancio manuale precedente usava il task SLEEP, mentre il launcher
appartiene al contesto UI. È stata corretta per richiedere il task UI e
non contare il breakpoint di ritorno del debugger come codice dinamico.
La prova sopra deriva dal percorso di avvio originale, senza lancio manuale.

## Interfaccia reale raggiunta: display secondario, principale, tasti (14 ottobre)

Dallo stato `amss_pxo_events.zip` il firmware non era bloccato: era lento. Il task SLEEP
è il loop di idle e passava la maggior parte del tempo a girare a vuoto. `tools/emulator.py`
con `--block-trace --timer-irq` ora porta il timer al prossimo tick quando il task corrente
è SLEEP (`SLEEP_LOOP=0x10dbd26`, TCB `0x1bf8fe0`): equivale a una attesa di interrupt, nessuna
istruzione del firmware viene saltata. Su 20 milioni di istruzioni il tempo virtuale avanzato
è circa 10 volte maggiore.

Dopo circa 1,5 miliardi di istruzioni il firmware apre `PhoneMenu.pxo`, `Insert_SIM.paf`
e `SubInsert_SIM.paf`, e mostra la schermata "Inserire USIM". Senza SIM è il suo comportamento
normale; la SIM non è emulata.

**Display secondario (96×96).** Porte `0x30000000` (comando) e `0x30100000` (dati). Un frame
sono 9216 scritture al registro 5; ogni frame inizia con una scrittura al registro 0x06.
Pixel RGB565. Il modello è in `tools/lcd_bus.py` (`sub_pixels`, `sub_frames`) e viene
esportato in `analysis/amss_sub_lcd.ppm`. Risultato verificato: `analysis/amss_sub_usim.png`.
I registri 0x50-0x55, 0x2a/0x3a/0x4a, 0x2b/0x3b/0x4b restano senza significato noto.

**Display principale in modalità byte.** Con il sensore flip "aperto" il principale non
usa più la modalità a 16 bit del primo avvio: il comando è `registro<<8`, ogni scrittura dati
porta un byte nei bit 15:8 (il byte basso, 0x00 o 0x80, viene ignorato) e un registro o
pixel richiede due scritture, byte alto per primo. Un frame sono 77440 scritture
(176×220×2). Verificato: `analysis/amss_main_flip_open.png` ("Inserire scheda USIM", barra di
stato, SOS). Il significato del byte basso costante non è stato chiarito.

**Sensore flip (ipotesi).** `tools/gpio_inputs.py`, opzione `--flip open|closed`. Il firmware
legge il bit 2 di `0x48000060` (0xeaddf6) e il bit 13 di `0x84000170` (helper 0xeadcc2).
Con il flip aperto il firmware passa a disegnare sul principale; con il flip chiuso solo sul
secondario. Non è confermato quale dei due bit sia necessario né la polarità in assoluto,
solo che l'effetto osservato è coerente. Il telefono è un flip.

**Tastiera.** `tools/keypad.py`: oltre alla scansione 5×7, la linea `0x84000170` bit 9
(letta a 0x1443928) deve essere alta quando un tasto è premuto, altrimenti il firmware non
esegue la scansione completa. Nuove opzioni: `--press RIGA,COL` (tasto tenuto per tutto il
run) e `--keys-file` (file riletto durante l'esecuzione, usato dalla finestra). Con il flip
chiuso, solo sei posizioni risvegliano il display secondario: (0,5), (1,5), (1,6), (2,5),
(2,6), (3,6) (`tools/probe_keys.py`, `analysis/key_probe.json`). Le etichette dei tasti non
sono note. La prova con il flip aperto non è conclusiva: il display principale si ridisegna
continuamente, quindi il confronto fra immagini non distingue la reazione ai tasti.

**Finestra.** `python3 tools/window.py` mostra i due display, il flip, 35 pulsanti
(per posizione di matrice) e mappa 35 tasti del PC. Il firmware gira in un solo processo; i
frame completati sono pubblicati come PPM con `--live-dir`. Provata in un display virtuale.

**Limiti noti.** Nessuna SIM: servono UIM/USIM (ISO 7816) con IMSI di un operatore valido.
Il firmware contiene le normali personalizzazioni (rete, sottoinsieme, service provider,
corporate); non è stato trovato un controllo "solo H3G" in chiaro. L'eventuale blocco
dipende dagli NV, e il backup NV originale non è stato ripristinato. Il DSP resta una risposta
HLE; non è provato alcun funzionamento di rete, audio o fotocamera.

## Indagine sul driver UIM/USIM (non completata)

Strumenti aggiunti, tutti di sola osservazione: `tools/task_stack.py` (stack salvato di un task
REX da un checkpoint), `tools/gpio_watch.py` (letture dei GPIO con PC chiamante),
`tools/rex_signal_watch.py` (segnali `rex_set_sigs` a UIM/GSDI/GSTK/UI/PS; da una finestra
partita dopo l'avvio non registra nulla, l'inizializzazione avviene prima) e un censimento
degli accessi MMIO con PC (`U310_MMIO_CENSUS=1`, chiave `mmio_census` nel report).

Fatti verificati nel checkpoint `f4.zip`:
- Il task UIM (TCB `0x1c03c54`) è il driver Qualcomm `uim`: ciclo principale in `0xa3e26a`,
  attesa `rex_wait` con maschera `0x61ff`, segnali pendenti `0x80000200`. Il bit `0x200` non
  è nella maschera di attesa. All'avvio chiama `0xa3dca8` (inizializzazione code/timer) e
  `0xb5c18c(0x22)`, una tabella di clock regime, non registri hardware della UART.
- Il task GSDI (TCB `0x1c0b40c`, ciclo in `0x128b5f8`, attesa in `0x10ec350`) è in attesa sulla
  propria coda comandi: nessuno gli ha inviato un comando di inizializzazione scheda.
- Nei 150 milioni di istruzioni analizzati il driver UIM non accede a nessun registro hardware:
  l'unico accesso rilevante è `0x80003404` (da `0xb5c1f8`, clock). Il firmware non sta quindi
  provando a parlare con la scheda, e non sono ancora stati identificati né il registro UART
  UIM né la linea di rilevamento scheda.
- Non è stato trovato un controllo "solo H3G" in chiaro. Il firmware contiene le personalizzazioni
  GSDI standard (rete, sottoinsieme, service provider, corporate) e stringhe `Hutchison` e
  `H3G_INFO` per la UI.


### Avvio da zero e censimento hardware

Nuova opzione `--nand-from-checkpoint file.zip`: CPU da zero (cold boot) sulla NAND salvata nel
checkpoint, senza ripristinare RAM e task. Con questa (300 milioni di istruzioni,
`analysis/cold300.zip`) è stato fatto un censimento completo degli accessi MMIO con PC
(`U310_MMIO_CENSUS=1`). Altri strumenti di sola osservazione: `tools/entry_watch.py`
(`U310_ENTRY_WATCH=0xaddr,...`: r0, r1, lr alle chiamate), `tools/task_coverage.py`
(`U310_COVERAGE=UIM,GSDI`: blocchi eseguiti con quel task corrente; include anche gli interrupt,
quindi i conteggi alti sono il gestore del timer) e `tools/find_callers.py` (chiamanti statici
BL/BLX di un indirizzo).

Risultati:
- `0x61800000` non è la UIM: è il controller MMC/SD. `mmc_init_real()` (messaggi "clock start
  failed", "END CMD40 never came") scrive e interroga i registri +0x00..+0x30 con timeout di
  `0x16e360` iterazioni; senza scheda SD i polling di `0x61800004` arrivano a circa 9 milioni
  di letture. È solo tempo perso nell'emulazione, non il blocco della SIM.
- Nei 300 milioni di istruzioni dell'avvio il driver UIM non accede a nessun registro hardware
  della scheda. Lo stato UIM (byte `0x17f3a58`) vale 7. Il ciclo principale (`0xa3e26a`) attende
  comandi sulla coda `0x1d4a67c`, che è citata solo dal modulo UIM stesso. Nessun comando
  (segnale `0x2`) viene mai inviato a UIM, e GSDI non riceve comandi sulla propria coda: UIM
  riceve solo il segnale timer `0x1` (82 volte).
- Il task principale (`tmc.c`, ciclo in `0xd2e264`) è in attesa sui segnali `0x2`/`0x4`.
- Altri accessi hardware dell'avvio (GPIO `0x48000000..3c`, clock `0x80003404`, timer
  `0x80003450`, controller `0x84001xxx`) sono nel report con `mmio_census`; nessuno è stato
  associato alla UIM.

Quindi il firmware non avvia mai la sequenza di accensione della scheda: manca il primo comando
GSDI/UIM, non la risposta della scheda. Per proseguire va individuato chi dovrebbe inviarlo
(funzione di accodamento comandi di GSDI, e i suoi chiamanti) e quale evento o risposta
hardware/DSP/NV lo precede. Solo dopo ha senso scrivere UART UIM, ATR e file system USIM.
Non implementati: UART UIM, ATR, USIM, ripristino NV originali.

### Prova di iniezione comando UIM (negativa)

`tools/probe_uim_cmd.py` (da `tools/`, `U310_MMIO_CENSUS=1`): inserisce un comando nella coda UIM
`0x1d4a67c` con le funzioni originali (`q_get 0x7c0720` sulla coda libera `0x1d4a688`, `q_put
0x7c0758`, `rex_set_sigs 0x8a04fc`) e poi lascia girare il guest da `cold300.zip`. L'id comando è
il halfword a +0x10 del buffer. In stato UIM 7 il ciclo (`0xa3e4fc`) accetta solo gli id `0x11a` e
`0x114`; il resto viene rifiutato.

Risultato con `0x11a` e `0x114`: il comando viene prelevato e il buffer torna alla coda libera
(20 su 20), ma lo stato UIM resta 7 e non compare nessun nuovo registro hardware (solo i soliti
`0x60000024`, `0x84001400`, `0x84001474`). I campi del buffer oltre l'id (stato, protocollo,
slot, funzione di report, coda di ritorno a +0x0c) sono azzerati o lasciati come li ha il buffer
libero, quindi questa prova non esclude che l'id o i campi siano sbagliati. Nessun accesso a una
UART della scheda: la mappa dei registri UIM resta sconosciuta.

Attenzione: `task_coverage` attribuisce al task corrente anche i blocchi del gestore IRQ, quindi
l'elenco "blocchi nuovi" non è utilizzabile da solo per capire cosa fa il driver.

### UIM: l'hardware esiste e il driver parte con il comando giusto (14 ottobre, sera)

Correzione di un errore del censimento MMIO: la pagina `0x84000000` è mappata direttamente e **non
rientra** nel conteggio (`mmio_census` / `mmio`). Gli accessi a `0x84000c80..0x84000cff` non erano
quindi visibili. `tools/uim_watch.py` (sempre attivo nel target amss, chiave `uim_watch`) li registra
con compressione delle ripetizioni.

Fatti verificati:
- La UART della scheda è a `0x84000c80` (driver `uimdrv.c`, funzione di accensione `uim_power_up`
  in `0xb6b0a2`). Registri osservati: `+0x0c` stato (il driver attende il bit 0 con timeout
  di 40.000 cicli: messaggio "No ATR in 40,000 clk cycles"), `+0x18` comando (`0x60`, `0x10`, `0x30`,
  `0x40`, `0x80`, `0x20`, `0x04`, `0xc0`, `0x01`), `+0x1c` maschera interrupt (`0x1c`, poi `0`),
  altri a `+0x30`, `+0x38..+0x40`, `+0x4c`, `+0x50`. Interpretazione dei registri come UART
  Qualcomm: ipotesi, non verificata.
- Il comando UIM `0x114` (e `0x11a`) iniettato con `tools/probe_uim_cmd.py` fa partire la sequenza
  reale: reset della UART, configurazione, abilitazione ricezione, attesa dell'ATR, timeout e
  nuovo tentativo con spegnimento. Gli id dei comandi sono gli stessi che il ciclo UIM accetta in
  stato 7 ("SIM in power down state"). `0x11c`, l'id che MMGSDI usa per l'accensione scheda
  (`mmgsdi_gen.c`, `0x145ddac`), viene invece rifiutato in stato 7.
- `tools/uim_uart.py` (`--uim-card`, sperimentale): UART inferita con stato e FIFO di ricezione
  e un ATR minimo `3b 90 11 00`. Con il comando `0x01` al registro `+0x18` il driver legge il
  byte pronto ed esce dall'attesa. Poi si ferma: manca la consegna tramite interrupt (la maschera
  `0x84000250` a fine prova è `0x398007f1`, uguale con e senza comando: nessuna sorgente UART
  risulta abilitata) e la lettura dei dati (registro di ricezione non ancora individuato).
- L'API originale `mmgsdi_card_pup` (`0x88dd80`, `mmgsdilib.c`) è utilizzabile da un task in modalità
  supervisor (`tools/probe_mmgsdi_pup.py`): con client id 0 ritorna 0 (successo). REX considera
  "interrupt" sia la modalità IRQ sia la modalità di sistema (`0x1f`): la chiamata va fatta in
  modalità `0x13` con IRQ abilitati, altrimenti scatta l'asserzione di memheap. Dopo la chiamata
  GSDI/MMGSDI risulta con un comando in attesa della risposta UIM ("MMGSDI Cmd Pending for UIM
  response", ripetuto dal timer di sanità `0x800000`).
- Il flag che abilita il resto del driver (`0x1d4bc38`/`0x1d4bc39`) viene impostato dalla routine
  di risposta ATR (`0x10e6232`, "The UIM is operating under T=%d").
- Nessuno dei task (GSDI, UI, TMC) invia spontaneamente il comando di accensione nell'avvio
  osservato; resta da capire cosa dovrebbe farlo.

Strumenti nuovi (solo osservazione, salvo `--uim-card` e le sonde di iniezione): `tools/uim_msgs.py`
(stringhe dei messaggi di debug inviati da un intervallo di codice), `tools/climb_callers.py`
(catena dei chiamanti), `tools/probe_mmgsdi_pup.py`.

Prossimi passi, nell'ordine: (1) trovare il vettore di interrupt della UART UIM (ISR in
`uimdrv.c`) e il registro di ricezione; (2) consegnare l'ATR e vedere se il driver prosegue con la
PPS e i comandi APDU; (3) modellare la USIM (file system UICC: EF_DIR, ADF USIM, EF_IMSI con
222-99, EF_AD, EF_LOCI, EF_UST, EF_ARR) rispondendo ai comandi SELECT/READ/STATUS/VERIFY;
(4) far partire il comando di accensione dal percorso originale (oggi solo da iniezione).
Il blocco H3G non è stato incontrato in nessun punto: l'unica verifica possibile resta quella con
la USIM di prova.

### UIM: ATR consegnato correttamente (14 ottobre, notte)

- La UART UIM usa il **vettore di interrupt 28** (voce `0xb6aee3` nella tabella ISR `0x1764b10`, 8 byte
  per voce; il dispatcher IRQ è in `0xd1217a`, legge `0x840002b0`). Registri confermati: `+0x0c`
  stato (bit 0 = byte pronto), `+0x14` dati in ricezione, `+0x18` comandi (`0x10` = reset ricevitore,
  `0x01` = abilita ricezione), `+0x1c` maschera interrupt, `+0x24` stato interrupt (bit 4 = livello RX).
  Il gestore (`0xb6aadc`) legge tutti i byte disponibili in un solo giro.
- Errore trovato e corretto nel modello: rialzare l'IRQ a ogni lettura del registro dati annidava il
  gestore (non rientrante) e l'ATR veniva memorizzato in ordine inverso, quindi il driver lo
  scartava ("Recd Command Response Signal", poi `uim_process_cmd_err` e `uim_power_down`). Ora
  `tools/uim_uart.py` alza l'interrupt una sola volta alla consegna.
- Con un ATR USIM realistico (22 byte con TCK o 21 senza; vedi `FULL_ATR`) il driver ora conserva
  l'ATR in ordine corretto e non spegne più la scheda al primo tentativo: l'avvio prosegue con il
  messaggio di sistema successivo. Non è ancora verificato che l'ATR sia accettato per intero
  (TCK sì/no) né cosa fa il driver dopo.
- Strumenti: `tools/msg_watch.py` (`U310_MSG_WATCH=N`: messaggi di debug del firmware con
  argomenti), `tools/atr_trace.py` (`U310_ATR_TRACE=N`: blocchi, byte letti/memorizzati, buffer),
  `tools/probe_sim_bringup.py` (iniezione reset UIM e `mmgsdi_card_pup`).
- Il percorso naturale dell'avvio tenta già da solo 5 volte "first attempt to reset the card": non
  serve iniettare comandi; serve solo che la scheda risponda correttamente.

### USIM emulata: il firmware riconosce la scheda e chiede il PIN (14 ottobre, notte)

Stato raggiunto con `--uim-card` (tutto sperimentale; la scheda è un modello, non un dump):
- **Livello UART** (`tools/uim_uart.py`): ATR consegnato a ogni reset, un solo interrupt per consegna,
  registro trasmissione `+0x10`, **eco** di ogni byte trasmesso nel ricevitore (linea a filo unico),
  risposte della scheda accodate e un interrupt per ogni scrittura TX.
- **Scheda** (`tools/usim_card.py`, 17 test in `tools/test_usim_card.py`): T=0, PPS (echo), SELECT
  (id, AID, percorso; risposta 61xx + GET RESPONSE con FCP), READ BINARY/RECORD, SEARCH RECORD
  semplice e avanzata (indicazione `04` = dall'offset), STATUS, VERIFY, UNBLOCK (query), TERMINAL
  PROFILE/RESPONSE, UPDATE BINARY/RECORD. CLA `A0` risponde `6E00`, così il driver usa UICC.
  File: MF (EF_DIR, ICCID, PL, ARR, DF_TELECOM), ADF USIM con IMSI 222-99, ACC, LOCI, PSLOCI, AD, UST,
  HPPLMN, SPN "H3G", LI, FPLMN, GID1/2, chiavi, ecc. Contenuti plausibili, non reali.
- **Sequenza osservata** (da `analysis/…json`, chiave `uim_uart.apdus`): SELECT MF → ICCID →
  TERMINAL PROFILE → EF_DIR (SEARCH per l'AID) → ARR → SELECT ADF USIM → EF_ECC, SPN, PL → VERIFY e
  RESET RETRY COUNTER (query, `P3=0`) per PIN1 e PIN universale → STATUS periodico.
- **PIN**: il firmware si aspetta uno stato coerente. Con PIN abilitato (PS_DO `0x80` nella FCP) e
  query VERIFY → `63C3`, UNBLOCK → `63CA`, procede e il display mostra **"Inserire PIN"**. Con il PIN
  disabilitato o già verificato (`pin_prompt=False`) resta in un ciclo VERIFY/UNBLOCK senza fine:
  causa non ancora capita (probabile controllo che pretende `63Cx` con PIN abilitato).
- **Schermo**: il display secondario mostra anche il logo "3" (H3G) di avvio e poi "Inserire PIN". Per
  proseguire va digitato il PIN con i tasti (default del modello `0000`, parametro `pin` di `UsimCard`).
- Errori corretti nel modello: dati di un comando che iniziano con `0xFF` scambiati per PPS; stato
  della scheda non azzerato a ogni reset; SEARCH RECORD avanzata mancante.

Prossimo passo: mappare le cifre della tastiera (finestra aperta sul display principale) e inserire il
PIN; poi verificare cosa chiede il firmware dopo la registrazione.

## Audio (stato)

- `tools/audio_hle.py` (`--audio`, attivo da `tools/window.py`): modello del servizio audio, non del DSP.
  Il firmware risolve da solo l'id del tono in due frequenze (`0x113c028`) e le stampa come `TONE: %x, %x`;
  il modello le legge da lì, sintetizza e invia a `pacat`. Toni dei tasti: funzionanti.
- File audio dal lettore multimediale (`[LGOEM_Play_AudioPlayer]`): il percorso è letto dal buffer del firmware
  (pagina 0x1bf4000), il file originale è trovato in `extracted/MEDIA` e riprodotto con ffplay (MIDI via fluidsynth).
  Verificato con "01 Clock Bell.aac". Formati senza decoder host (MMF/SMAF) sono saltati. Suonerie di sistema e avvio: non ancora agganciati.
- Ricerca del percorso reale verso il QDSP: la richiesta di tono arriva a `qdsptask.c` (0x10d6xxx), carica l'immagine
  ("QDSP image loaded"), poi il suono viene scartato ("Sound change, no tone"): manca la risposta del DSP
  (evento di abilitazione app). I comandi verso il DSP li scrive il driver vocoder (0x126axxx, finestre 0x582xxxxx).
  Nessun comando/campione audio raggiunge la memoria DSP finché il DSP non risponde. Strumenti: `tools/tone_calls.py`,
  `tools/disas.py`, `tools/dsp_trace.py` (ora traccia anche le letture).
- Layout tasti corretto in `window.py`: SOFT_R=(3,4), UP=(1,4) (verificato dai menu).
- `tools/qdsp_model.py` (attivo con `--audio`, o `U310_QDSP_IRQ=1`): modello del dispositivo QDSP. Protocollo ricavato dal driver ARM:
  * IRQ 10 -> `qdsptask.c` inoltra alle app abilitate; l'ISR vocoder (0x126a23a) legge lo stato DSP.
  * Parola "modulo pronto" (0x580008ce / 0x58007b84, letta da 0x126adb6): il driver (stato in 0x19ae45c) attende -1
    (immagine avviata, stati 1-4) poi 1 (modulo inizializzato, stato 5).
  * Comandi ARM->DSP: registro comando (halfword, 0 = libero; 0xfffe = DSP non avviato) a 0x5820005e (immagine voc 1)
    o 0x58206e22 (immagine 0xc), payload a +2, campanello 0x58c00004 = 1. Il DSP libera il registro.
  * Comando 0x301 = configurazione codec; **0x302 = generatore di toni**: payload[0..1] = coefficienti oscillatore
    c = 2*cos(w) in Q13 a 8 kHz (0x34a4 -> 770 Hz, 0x1fe2 -> 1336 Hz), zeri = stop. `audio_hle` sintetizza da questo comando.
  * SBI (0x84000d00, bus PMIC/codec Adie): +0x04 slave, +0x10 parola (bit15 lettura, 14:8 registro, 7:0 dato),
    +0x20 start, +0x2c bit0 fine, risultati +0x14/+0x18/+0x1c. Modellato con un file di registri per slave.
  Da fare: immagine 0xc (sintesi MIDI/DTMF/file): ripete "QDSP image loaded = 0xc" e il comando 0x301 senza avanzare;
  volume del tono (payload[2..4]) non decifrato; decodifica file (AAC/MIDI/MP3) ancora tramite lettore host.

## Rete / operatore (stato)

- Il telefono non passa da solo a ONLINE: `cm_ph_cmd_oprt_mode` resta 9 (OFFLINE_IF_NOT_FTM). Forzandolo (`tools/probe_oprt.py 5`,
  funzione 0xd1a449: cb, data, client=-1, mode) partono MMOC -> CMREGPRX ("Send SIM_AVAILABLE_REQ") -> task REG, poi lo stallo:
  `CMREGPRX` aspetta "sim avail conf" da REG; REG legge IMSI/LOCI dalla cache GSDI ma non passa al task MM (0 blocchi eseguiti).
  Prima ancora del livello radio manca quindi la risposta NAS interna (causa non ancora trovata: REG finisce in 0x16833xx).
- Il L1 WCDMA (RRC attivo) e GSM L1 restano in stato "stopped": per una cella simulata servirebbe emulare il livello MPH/PH sotto RR/RRC.
- Il nome operatore viene da una tabella interna (UTF-16 ~0x115f340: "3 ITA", "3 AT", "3 UK") cercata dopo la registrazione.
- Strumenti: probe_oprt.py, probe_subscription.py, probe_sigs.py/probe_sigs2.py (segnali REX), probe_tasks.py, probe_reg.py, find_msg_refs.py, msg_users.py.

## Distribuzione e installazione (14 ottobre, notte)

- `./u310 install|run|reset|info` (`tools/u310.py`, `tools/provision.py`, `tools/firmware_manifest.py`): installazione da
  zero riproducibile dai soli tre file originali, verificata da una copia pulita (80 s): avvio su flash sintetica con
  `--synthetic-ssikyu` (250M istruzioni, FS pronto), `install_modules.py --fast` per 129 moduli e 550 risorse, paese dal Flex.ini,
  avvio a freddo fino alla home H3G. La flash installata è `data/phone.zip` e viene riscritta allo spegnimento
  (`--save-nand`, SIGTERM/SIGINT, solo dopo 2 miliardi di istruzioni; copia precedente in `.bak`).
- `tools/make_release.py`: archivio con solo codice. `tools/settings.py` + finestra: IMEI/Bluetooth/PIN/velocità.
- IMEI e indirizzo Bluetooth: `tools/nv_override.py` serve le voci NV 550 e 447 sulla coda dei comandi NV (0x10d219a)
  completando la richiesta con `rex_set_sigs` (**0x1265dec**; 0x1265da8 è `rex_clr_sigs`, scambiato in precedenza).
  Prova: sparisce "Default IMEI 00440015202000". Il byte order dell'indirizzo BT è un'ipotesi; il BT resta spento (nessun chip emulato).
- MMC: il modello del clock aggiorna il bit di stato alla scrittura invece che a ogni lettura (il firmware legge il registro
  milioni di volte aspettando una scheda assente) e la pagina 0x61800000 è esclusa dal censimento hook.
- Strumenti: `U310_HEARTBEAT`, `kill -USR1` (traceback), `U310_PC_HITS`, `U310_NV_LOG`, `U310_TASK_MMIO`.

## Rete simulata, SIM con profilo, prossimi blocchi (15 ottobre)

- **Perché il telefono non registrava**: (1) senza IMEI valido il NAS non partiva (`--imei`); (2) la SIM simulata aveva PLMN 229-99 in
  EF_LOCI (22 f9 99) invece di 222-99 (22 f2 99); (3) mancavano 405 voci NV di calibrazione radio: il lettore a 0x18b8d6 restituisce
  errore 4 se una voce obbligatoria è NOT_ACTIVE e `rfm_init` falliva ("going offline"). `tools/rf_nv_items.py` + `--rf-defaults`
  servono record a zero (via `nv_override`). (4) Il telefono non va ONLINE da solo: `cm_ph_cmd_oprt_mode(ONLINE)` (0xd1a449) viene
  chiamata da `netsim` ~600 chunk dopo `cm_ph_cmd_subscription_available`.
- **`tools/netsim.py` (`--netsim`)**: sostituisce RRC/L1/MDSP sotto il NAS. Intercetta `q_put` (0x1279116) sulla coda RRC (0x183e0c8),
  risponde a RRC_SERVICE_REQ con RRC_SERVICE_CNF costruito con l'allocatore MM (0x12e0748) e il sender (0x12de574), chiamati con
  `tools/guest_call.py` (chiamata sincrona di funzioni guest a un punto sicuro: SVC, IRQ aperti). Layout recuperato dal gestore MM
  (0x10c5f98): +8 stato, +0xd PLMN (mcc[3], n cifre MNC, mnc[3]), +0x14 LAC presente, +0x1c LAC, +0x24 n. domini CN, +0x28 voce valida.
  Risultato: MM registra "Serving LAI PLMN 22 f2 99, LAC 1", CM_CAMPED_IND, MMR_REG_REQ, "SERVICE IS AVAILABLE".
- **Mancano**: livello di segnale (tacche) e nome operatore. Il CM ha già l'oggetto SS a 0x19bcc68 (rssi di default 125 a +0x46), ma i
  rapporti RSSI vengono da RR/RRC (L1: 0x149f07c), non da REG; PhoneMngr.pxo calcola le tacche da `pSsInfo->rssi` (evento CM SS).
  Altri comandi MM->RRC non gestiti: 0x500000a, 0x500000c, 0x500000d. Il L1 WCDMA richiede inoltre il byte "ready" a 0x50001faa
  (aggiunto in `mdsp_management`, `U310_NO_WCDMA_READY=1` lo disattiva).
- **SIM con profilo** (`tools/sim_profile.py`, `--sim NOME`, finestra Impostazioni): IMSI, ICCID, numero (EF_MSISDN 0x6f40, UST servizi 19 e 21),
  nome operatore, PIN/PUK; le scritture del telefono (UPDATE BINARY/RECORD) sono salvate in `<nome>.state.json` e ricaricate.
- **microSD**: il controller MMC è a 0x61800000 con registri propri (non PL180): +0x00 clock (1 stop, 2 start), +0x08 comando, +0x10 avvio,
  +0x14 maschera, +0x18, +0x28/0x2c/0x30 dati; driver `mmc_init_real` (CMD1/2/3/9/41...). Da decifrare (risposte R1/R2/R3, FIFO dati).
- **Bluetooth**: il task BT parla con il chip dopo la lettura di NV 447; serve il controller HCI su UART + profili audio.
- Strumenti nuovi: `msg_func.py`, `msg_users.py` (generalizzato), `msg_region.py`, `net_probe.py`, `exp_plmn.py`, `U310_WATCH_WRITES`,
  `U310_WATCH_ACCESS`, `U310_PC_HITS` (fino a 3000 hit).


## Rete, segnale e operatore (risolto)

Obiettivo: il telefono mostra "3G", le tacche e il nome operatore ("H3G") come quello reale. Percorso ricavato dal firmware:

- **Registrazione**: MM interpreta `RRC_SERVICE_CNF` (id 0x67). Le informazioni di dominio CN sono voci da 16 byte da +0x28:
  `+0` dominio (0 = CS, 1 = PS), `+4` lunghezza (>= 2), `+8` dati. CS: T3212 (0 = nessun aggiornamento periodico) e flag (bit 0 = IMSI attach
  richiesto); PS: RAC e flag (bit 0 = NMO I). Con la voce CS mancante MM stampa "The CS specific domain information must be atleast 2 bytes in length"
  e REG ripiega sul GSM (servizio limitato). Con la voce CS corretta e `EF_LOCI` della SIM coerente (stesso LAI/LAC della cella, stato
  "aggiornato", TMSI valido) MM stampa "Same Lai-LU not required" e il servizio risulta completo: nessun Location Update via aria da simulare.
- **Messaggi RRC verso MM**: id 0x64 EST_CNF, 0x65 REL_IND, 0x66 SYNC_IND, 0x67 SERVICE_CNF, 0x68 SERVICE_IND, 0x6a PLMN_LIST_CNF, 0x6e OPEN_SESSION_CNF,
  0x6f CLOSE_SESSION_IND, 0x70 CLOSE_SESSION_CNF, 0x73 MODE_CHANGE_CNF, 0x74 STOP_WCDMA_MODE_CNF (allocatore 0x12e0748 accetta 0x64-0x78).
- **Segnale**: il report arriva al task CM come elemento sulla coda dei report (0x19c0f4c) con comando 0x29, seguito dal segnale REX 2 al TCB di CM
  (0x1be9eb8). Il valore e' in `msg+0x18` (RSSI in -dBm; 125 = nessun segnale). CM copia l'RSSI nel record 0x19bd6c8 e invia l'evento RSSI
  (tipo 1) ai client; PhoneMngr lo riceve come `PDK Post Event 10400`. Le tacche vengono da due misure: RSSI (soglie 91/101/111/115 -> livelli 4..1)
  e Ec/Io (halfword a `ssinfo+0x20`, valore/2 in dB con soglie 13/13/15/18), vince la peggiore. L'Ec/Io proviene da `0x1e772b0+0x1a`; `netsim`
  lo deriva dall'RSSI. Livello 0: nessuna tacca. Tacche e icona "3G" compaiono solo con `srv_status == 2` (NmInfo+4).
- **Nome operatore**: "H3G" viene dal firmware (tabella interna + SPN della SIM) una volta registrato.
- Impostazione: `--rssi` (default 65), `--signal-file` riletto durante l'esecuzione; il menu "Rete" della finestra scrive il file.

## Ingressi GPIO scoperti

- Bit 5 di `0x8400016c` = auricolare NON inserito (il valore 0 di default faceva comparire l'icona cuffie e il profilo "Auricolare").
  Modello `HeadsetJack` in `gpio_inputs.py`; la finestra ha "Inserisci/estrai auricolare" (`--headset-file`).
- Bit 3 di `0x8400016c` = rilevamento microSD.

## Suoni (aggiornamento)

- Anteprima suoneria dal menu Profili d'uso > Modifica > elenco > Play: `SNDAPI_Play_AudioPlayer=<percorso>` con sorgente CMX_SOURCE_EFS;
  il percorso (es. `/LGAPP/Media/Sounds/Default sounds/Ring1.mid`) e' gia' intercettato da `audio_hle`. I file `.mmf` (SMAF MA-3) non
  hanno decoder ffmpeg ("MIDI like format ... unsupported").
- Il suono di accensione ("Power On.aac") non viene richiesto dal firmware nell'avvio emulato (nessuna chiamata AudioPlayer).

## microSD: lettura e scrittura verificate

- La scrittura (CMD24/CMD25) si completa solo con tre bit di stato che il driver `mmc_write_i` attende: bit 6 (0x40) = FIFO pronta a ricevere
  la parola (ciclo a 0x3680c4), bit 11 e bit 12 (0x1800) = blocco ricevuto e programmato (ciclo a 0x368276). Senza di essi la scheda restava in stato
  RCV, CMD13 veniva ripetuto 2000 volte e il telefono mostrava "Memoria insufficiente per salvare".
- Dopo la correzione il telefono, entrando in "Memoria esterna", crea da solo `Images`, `Videos`, `Sounds`, `Others` (visibili con `mdir`),
  e "Aggiungi nuovo" crea cartelle reali nell'immagine.
- L'orologio del telefono (data dei file) parte dal 2006-01-01.
