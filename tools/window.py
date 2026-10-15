#!/usr/bin/python3
"""Finestra dell'emulatore LG U310: display principale e secondario, tastiera come sul telefono.

Il firmware gira in un solo processo (modalità veloce, a tempo reale). I tasti premuti sono scritti
in un file che il modello della tastiera rilegge; i fotogrammi completati arrivano come file PPM.
La disposizione dei tasti riprende quella del telefono aperto. Le posizioni nella matrice sono state
ricavate provando ogni tasto sul firmware (tools/probe_keys.py); END è il tasto di accensione,
una linea separata della matrice.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib

ROOT = Path(__file__).resolve().parents[1]
(ROOT / 'analysis').mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / 'tools'))
import provision  # noqa: E402

NAND_IMAGE = provision.PHONE  # flash del telefono installato (si aggiorna da sola allo spegnimento)
BOOT_DONE = 2_000_000_000  # istruzioni dopo le quali lo stato della flash è coerente e viene salvato

# Posizioni (riga, colonna) nella matrice 5x7.
KEYS = {
    'SOFT_L': (0, 4), 'SOFT_R': (3, 4), 'BACK': (4, 4), 'C': (0, 3), 'OK': (2, 3),
    'UP': (1, 4), 'DOWN': (4, 3), 'LEFT': (1, 3), 'RIGHT': (2, 4), 'SEND': (3, 3),
    'MENU': (0, 2), 'CONTACTS': (0, 0), 'MUSIC': (0, 1), 'VOL_UP': (1, 5), 'VOL_DOWN': (2, 5),
    '1': (1, 0), '2': (1, 1), '3': (1, 2), '4': (2, 0), '5': (2, 1), '6': (2, 2),
    '7': (3, 0), '8': (3, 1), '9': (3, 2), '*': (4, 0), '0': (4, 1), '#': (4, 2),
}
POWER = 'END'  # tasto di accensione: linea separata, non è nella matrice

# (nome, etichetta, riga, colonna, larghezza, stile)
LAYOUT = [
    ('SOFT_L', '—', 0, 0, 2, 'soft'), ('SOFT_R', '—', 0, 3, 2, 'soft'),
    ('BACK', 'BACK', 1, 0, 1, 'func'), ('UP', 'TV', 1, 2, 1, 'dpad'), ('C', 'C◄', 1, 4, 1, 'func'),
    ('LEFT', '♫', 2, 1, 1, 'dpad'), ('OK', 'OK', 2, 2, 1, 'ok'), ('RIGHT', '✉', 2, 3, 1, 'dpad'),
    ('SEND', 'SEND', 3, 0, 1, 'send'), ('DOWN', '☺', 3, 2, 1, 'dpad'), (POWER, 'END', 3, 4, 1, 'end'),
    ('CONTACTS', '☎', 4, 0, 1, 'func'), ('MUSIC', '♪', 4, 2, 1, 'func'), ('MENU', 'MENU', 4, 4, 1, 'func'),
    ('1', '1', 5, 0, 1, 'num'), ('2', '2 abc', 5, 2, 1, 'num'), ('3', '3 def', 5, 4, 1, 'num'),
    ('4', '4 ghi', 6, 0, 1, 'num'), ('5', '5 jkl', 6, 2, 1, 'num'), ('6', '6 mno', 6, 4, 1, 'num'),
    ('7', '7 pqrs', 7, 0, 1, 'num'), ('8', '8 tuv', 7, 2, 1, 'num'), ('9', '9 wxyz', 7, 4, 1, 'num'),
    ('*', '* +', 8, 0, 1, 'num'), ('0', '0 ␣', 8, 2, 1, 'num'), ('#', '# ⇧', 8, 4, 1, 'num'),
]
# Tastiera del PC -> tasto del telefono.
PC_KEYS = {
    Gdk.KEY_Up: 'UP', Gdk.KEY_Down: 'DOWN', Gdk.KEY_Left: 'LEFT', Gdk.KEY_Right: 'RIGHT',
    Gdk.KEY_Return: 'OK', Gdk.KEY_KP_Enter: 'OK', Gdk.KEY_BackSpace: 'C', Gdk.KEY_Escape: 'BACK',
    Gdk.KEY_F1: 'SOFT_L', Gdk.KEY_F2: 'SOFT_R', Gdk.KEY_F3: 'SEND', Gdk.KEY_F4: POWER,
    Gdk.KEY_m: 'MENU', Gdk.KEY_Page_Up: 'VOL_UP', Gdk.KEY_Page_Down: 'VOL_DOWN',
    Gdk.KEY_asterisk: '*', Gdk.KEY_numbersign: '#',
}
for digit in '0123456789':
    PC_KEYS[getattr(Gdk, 'KEY_' + digit)] = digit
    PC_KEYS[getattr(Gdk, 'KEY_KP_' + digit)] = digit

CSS = b'''
window { background: #3b3f46; }
.phone { background: #d9dce1; border-radius: 22px; padding: 12px; }
.lcd { background: #000; padding: 4px; border-radius: 6px; }
button { border-radius: 10px; padding: 6px 2px; font-weight: bold; color: #222; border: 1px solid #9ea3ab;
         background: #f3f4f6; box-shadow: none; }
button:active { background: #b9bec7; }
button.soft { background: #e5e7eb; min-height: 12px; }
button.dpad { background: #eceef2; }
button.ok { background: #7d8088; color: #fff; }
button.send { background: #8fd18f; }
button.end { background: #e58a8a; }
button.num { background: #fafafa; min-height: 30px; }
label.status { color: #dfe3ea; }
'''


class EmulatorWindow(Gtk.Window):
    def __init__(self, resume, flip_open, no_pin=True, cpu_mhz=45.0, scale=None):
        super().__init__(title='LG U310 — emulatore sperimentale')
        import settings
        self.settings_module = settings
        self.settings = settings.load()
        if cpu_mhz != 45.0:
            self.settings['cpu_mhz'] = cpu_mhz
        self.no_pin = no_pin and not self.settings['pin']
        self.cpu_mhz = self.settings['cpu_mhz']
        self.set_position(Gtk.WindowPosition.CENTER)
        self.work = Path(tempfile.mkdtemp(prefix='u310-'))
        self.keys_file = self.work / 'keys.txt'
        self.keys_file.write_text('')
        self.signal_file = self.work / 'signal.txt'
        self.headset_file = self.work / 'headset.txt'
        self.headset_file.write_text('0')
        self.held, self.power = set(), False
        self.resume, self.flip_open = resume, flip_open
        self.child, self.closed = None, False
        self.log = open(ROOT / 'analysis/window.log', 'a', buffering=1)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.scale = scale or (2 if Gdk.Screen.get_default().get_height() >= 1000 else 1)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_border_width(10)
        self.add(outer)
        outer.pack_start(self.build_menu(), False, False, 0)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        body.get_style_context().add_class('phone')
        outer.pack_start(body, False, False, 0)

        screens = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        body.pack_start(screens, False, False, 0)
        main_frame = Gtk.Box()
        main_frame.get_style_context().add_class('lcd')
        self.main = Gtk.Image()
        main_frame.pack_start(self.main, False, False, 0)
        screens.pack_start(main_frame, False, False, 0)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.START)
        sub_frame = Gtk.Box()
        sub_frame.get_style_context().add_class('lcd')
        self.sub = Gtk.Image()
        sub_frame.pack_start(self.sub, False, False, 0)
        side.pack_start(Gtk.Label(label='Display esterno'), False, False, 0)
        side.pack_start(sub_frame, False, False, 0)
        self.flip = Gtk.CheckButton(label='Flip aperto')
        self.flip.set_active(flip_open)
        self.flip.connect('toggled', self.on_flip)
        side.pack_start(self.flip, False, False, 0)
        for name, text in (('VOL_UP', 'Vol +'), ('VOL_DOWN', 'Vol −')):
            side.pack_start(self.make_button(name, text, 'func'), False, False, 0)
        screens.pack_start(side, False, False, 0)

        grid = Gtk.Grid(column_spacing=6, row_spacing=6, column_homogeneous=True, halign=Gtk.Align.CENTER)
        for name, text, row, column, span, style in LAYOUT:
            grid.attach(self.make_button(name, text, style), column, row, span, 1)
        body.pack_start(grid, False, False, 4)

        bar = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        config = Gtk.Button(label='Impostazioni…')
        config.set_can_focus(False)
        config.connect('clicked', self.on_settings)
        bar.pack_start(config, False, False, 0)
        outer.pack_start(bar, False, False, 0)
        self.status = Gtk.Label(label='Accensione in corso…')
        self.status.get_style_context().add_class('status')
        outer.pack_start(self.status, False, False, 0)
        hint = Gtk.Label(label='Tastiera PC: cifre, * #, frecce, Invio=OK, Backspace=C, Esc=BACK, F1/F2=softkey, '
                               'F3=SEND, F4=END (tieni premuto = spegne), M=MENU')
        hint.get_style_context().add_class('status')
        hint.set_line_wrap(True)
        outer.pack_start(hint, False, False, 0)

        self.connect('destroy', self.close)
        self.connect('key-press-event', self.on_pc_key, True)
        self.connect('key-release-event', self.on_pc_key, False)
        self.show_all()
        self.start()
        GLib.timeout_add(150, self.poll)

    def on_settings(self, _button):
        import random
        import sim_profile
        dialog = Gtk.Dialog(title='Impostazioni del telefono', transient_for=self, modal=True)
        dialog.add_buttons('Annulla', Gtk.ResponseType.CANCEL, 'Salva e riavvia il telefono', Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        dialog.get_content_area().add(grid)
        fields, row = {}, 0

        def add_entry(key, label, value, width=24):
            nonlocal row
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            entry = Gtk.Entry(text=str(value), width_chars=width)
            grid.attach(entry, 1, row, 1, 1)
            fields[key] = entry
            row += 1
            return entry

        add_entry('imei', 'IMEI (14 cifre, o 15 con controllo)', self.settings['imei'])
        add_entry('bt_addr', 'Indirizzo Bluetooth (AA:BB:CC:DD:EE:FF)', self.settings['bt_addr'])
        add_entry('cpu_mhz', 'Velocità emulata (MHz)', self.settings['cpu_mhz'])

        grid.attach(Gtk.Separator(), 0, row, 2, 1)
        row += 1
        grid.attach(Gtk.Label(label='SIM inserita', xalign=0), 0, row, 1, 1)
        combo = Gtk.ComboBoxText()
        for name in sim_profile.list_names():
            combo.append_text(name)
        names = sim_profile.list_names()
        combo.set_active(names.index(self.settings['sim']) if self.settings['sim'] in names else 0)
        box = Gtk.Box(spacing=6)
        box.pack_start(combo, True, True, 0)
        new_button = Gtk.Button(label='Nuova SIM…')
        box.pack_start(new_button, False, False, 0)
        grid.attach(box, 1, row, 1, 1)
        row += 1
        sim_fields = {}
        for key, label in (('msisdn', 'Numero di telefono (+39…)'), ('alpha', 'Etichetta del numero'),
                           ('spn', 'Nome operatore'), ('imsi', 'IMSI (15 cifre)'), ('iccid', 'ICCID (19-20 cifre)'),
                           ('pin', 'PIN'), ('puk', 'PUK')):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            entry = Gtk.Entry(width_chars=24)
            grid.attach(entry, 1, row, 1, 1)
            sim_fields[key] = entry
            row += 1
        pin_ask = Gtk.CheckButton(label='La SIM chiede il PIN all\'accensione')
        grid.attach(pin_ask, 0, row, 2, 1)
        row += 1

        def show_profile(*_args):
            profile = sim_profile.load(combo.get_active_text() or sim_profile.DEFAULT_NAME)
            for key, entry in sim_fields.items():
                entry.set_text(str(profile[key]))
            pin_ask.set_active(bool(profile['pin_enabled']))
        combo.connect('changed', show_profile)
        show_profile()

        def make_new(_button):
            ask = Gtk.Dialog(title='Nuova SIM', transient_for=dialog, modal=True)
            ask.add_buttons('Annulla', Gtk.ResponseType.CANCEL, 'Crea', Gtk.ResponseType.OK)
            name_entry = Gtk.Entry(placeholder_text='Nome della SIM')
            ask.get_content_area().add(name_entry)
            ask.show_all()
            if ask.run() == Gtk.ResponseType.OK and name_entry.get_text().strip():
                name = name_entry.get_text().strip()
                profile = dict(sim_profile.DEFAULTS, name=name,
                               imsi='22299' + ''.join(random.choice('0123456789') for _ in range(10)),
                               iccid='89399900' + ''.join(random.choice('0123456789') for _ in range(11)))
                sim_profile.save(profile)
                combo.append_text(name)
                combo.set_active(len(sim_profile.list_names()) - 1 if name in sim_profile.list_names() else 0)
                for index, existing in enumerate(sim_profile.list_names()):
                    if existing == name:
                        combo.set_active(index)
            ask.destroy()
        new_button.connect('clicked', make_new)

        reset = Gtk.Button(label='Ripristina stato di fabbrica…')
        reset.connect('clicked', lambda _b: (dialog.response(Gtk.ResponseType.CANCEL), GLib.idle_add(self.factory_reset)))
        grid.attach(reset, 0, row, 2, 1)
        row += 1
        error = Gtk.Label(xalign=0)
        grid.attach(error, 0, row, 2, 1)
        dialog.show_all()
        while dialog.run() == Gtk.ResponseType.OK:
            sim_name = combo.get_active_text() or sim_profile.DEFAULT_NAME
            candidate = dict(self.settings, imei=fields['imei'].get_text().strip(),
                             bt_addr=fields['bt_addr'].get_text().strip(), sim=sim_name)
            profile = dict(sim_profile.load(sim_name), pin_enabled=pin_ask.get_active(),
                           **{k: e.get_text().strip() for k, e in sim_fields.items()})
            try:
                candidate['cpu_mhz'] = float(fields['cpu_mhz'].get_text())
                self.settings_module.validate(candidate)
                profile['name'] = sim_name
                sim_profile.save(profile)
            except ValueError as exc:
                error.set_text(str(exc))
                continue
            candidate['pin'] = profile['pin_enabled']
            self.settings = candidate
            self.settings_module.save(candidate)
            self.no_pin, self.cpu_mhz = not profile['pin_enabled'], candidate['cpu_mhz']
            self.restart()
            break
        dialog.destroy()

    # ---- menu -----------------------------------------------------------------------------------------------
    def build_menu(self):
        bar = Gtk.MenuBar()

        def menu(title, items):
            root = Gtk.MenuItem(label=title)
            sub = Gtk.Menu()
            for label, handler in items:
                if label is None:
                    sub.append(Gtk.SeparatorMenuItem())
                    continue
                entry = Gtk.MenuItem(label=label)
                entry.connect('activate', lambda _w, h=handler: h())
                sub.append(entry)
            root.set_submenu(sub)
            bar.append(root)
        menu('Telefono', [('Installa firmware…', lambda: self.install_from_menu(False)),
                          ('Reinstalla da capo (cancella tutto)…', lambda: self.install_from_menu(True)),
                          ('Disinstalla tutto…', self.uninstall_all),
                          (None, None),
                          ('Ripristino di fabbrica…', self.factory_reset),
                          ('Riavvia il telefono', self.restart_plain),
                          ('Inserisci/estrai auricolare', self.toggle_headset),
                          (None, None),
                          ('Esci', self.close)])
        menu('SIM', [('Gestisci SIM e numero…', lambda: self.on_settings(None))])
        menu('microSD', [('Esplora la scheda (file, formattazione, dimensione)…', self.sd_browse),
                         ('Crea nuova scheda…', self.sd_create),
                         ('Inserisci immagine…', self.sd_insert),
                         ('Estrai la scheda', self.sd_eject),
                         (None, None),
                         ('Formatta la scheda…', self.sd_format),
                         ('Copia file dal PC nella scheda…', self.sd_copy_in),
                         ('Copia il contenuto della scheda sul PC…', self.sd_copy_out),
                         ('Informazioni sulla scheda', self.sd_info)])
        self.signal_levels = {'Nessun segnale': 124, 'Debole': 105, 'Medio': 95, 'Buono': 85, 'Ottimo': 65}
        menu('Rete', [(f'Segnale: {name}', lambda n=name: self.set_signal(n)) for name in self.signal_levels])
        menu('Impostazioni', [('IMEI, Bluetooth, velocità…', lambda: self.on_settings(None))])
        return bar

    def toggle_headset(self):
        inserted = self.headset_file.read_text().strip() != '1' if self.headset_file.exists() else True
        self.headset_file.write_text('1' if inserted else '0')
        self.status.set_text('Auricolare inserito' if inserted else 'Auricolare estratto')

    def set_signal(self, name):
        self.settings['signal'] = name
        self.settings_module.save(self.settings)
        self.signal_file.write_text(str(self.signal_levels[name]))
        self.status.set_text(f'Segnale simulato: {name}')

    def message(self, kind, text, detail=''):
        box = Gtk.MessageDialog(transient_for=self, modal=True, message_type=kind, buttons=Gtk.ButtonsType.OK, text=text)
        if detail:
            box.format_secondary_text(detail)
        box.run()
        box.destroy()

    def confirm(self, text, detail=''):
        box = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.YES_NO, text=text)
        if detail:
            box.format_secondary_text(detail)
        answer = box.run() == Gtk.ResponseType.YES
        box.destroy()
        return answer

    def choose(self, title, action, accept='OK', multiple=False, save_name=None):
        chooser = Gtk.FileChooserDialog(title=title, transient_for=self, action=action)
        chooser.add_buttons('Annulla', Gtk.ResponseType.CANCEL, accept, Gtk.ResponseType.OK)
        chooser.set_select_multiple(multiple)
        if save_name:
            chooser.set_current_name(save_name)
        result = None
        if chooser.run() == Gtk.ResponseType.OK:
            result = chooser.get_filenames() if multiple else chooser.get_filename()
        chooser.destroy()
        return result

    def run_background(self, work, after):
        """work(progress) runs in a thread (progress goes to the status line); after(error) runs in the GUI thread."""
        import threading
        result = {}

        def thread():
            try:
                work(lambda text: GLib.idle_add(self.status.set_text, text))
            except (ValueError, RuntimeError, OSError) as exc:
                result['error'] = str(exc)
            GLib.idle_add(lambda: after(result.get('error')))
        threading.Thread(target=thread, daemon=True).start()

    def install_wizard(self):
        """First start with no installed phone: ask for the firmware folder and install."""
        self.message(Gtk.MessageType.INFO, 'Il telefono non è ancora installato',
                     'Servono i file originali del firmware LG U310 V10a H3G (CODE, MEDIA e MODULE): non sono inclusi '
                     'nell\'emulatore. L\'installazione si fa una volta sola e richiede circa un minuto.')
        self.install_from_menu(False, first=True)

    def install_from_menu(self, wipe, first=False):
        if wipe and not self.confirm('Cancellare tutto e reinstallare da capo?',
                                     'Flash del telefono, impostazioni e dati andranno persi (le SIM e le schede microSD restano).'):
            return
        folder = self.choose('Cartella (o zip) con i file originali del firmware', Gtk.FileChooserAction.SELECT_FOLDER, 'Installa')
        if not folder:
            if first:
                self.status.set_text('Telefono non installato: usa il menu Telefono > Installa firmware…')
            return
        self.stop()
        self.status.set_text('Installazione in corso…')
        operation = provision.reinstall if wipe else provision.install

        def after(error):
            if error:
                self.message(Gtk.MessageType.ERROR, 'Installazione non riuscita', error)
                self.status.set_text('Telefono non installato: usa il menu Telefono > Installa firmware…')
            else:
                self.resume = None
                self.start()
        self.run_background(lambda progress: operation(folder, progress=progress), after)

    def uninstall_all(self):
        if not self.confirm('Disinstallare tutto?', 'Verranno eliminati la flash del telefono, le risorse estratte e le copie del '
                            'firmware. Le SIM e le schede microSD non vengono toccate. Per riusare il telefono servirà una nuova installazione.'):
            return
        self.stop()
        provision.uninstall(lambda text: self.status.set_text(text))
        self.message(Gtk.MessageType.INFO, 'Telefono disinstallato', 'Usa Telefono > Installa firmware… per ricominciare.')

    def factory_reset(self):
        if not provision.installed():
            self.message(Gtk.MessageType.INFO, 'Telefono non installato')
            return
        if self.confirm('Ripristinare il telefono allo stato di fabbrica?',
                        'Impostazioni, contatti e messaggi del telefono emulato andranno persi.'):
            self.stop()
            provision.reset(lambda text: self.status.set_text(text))
            self.resume = None
            self.start()

    def restart_plain(self):
        self.stop()
        self.resume = None
        self.start()

    # ---- microSD ----------------------------------------------------------------------------------------------
    def sd_current(self):
        path = self.settings.get('sd_image', '')
        return path if path and Path(path).exists() else None

    def sd_set(self, path):
        self.settings['sd_image'] = path
        self.settings_module.save(self.settings)
        self.restart_plain()

    def sd_browse(self):
        path = self.sd_current()
        if not path:
            self.message(Gtk.MessageType.INFO, 'Nessuna scheda inserita', 'Usa microSD > Crea nuova scheda… o Inserisci immagine….')
            return
        from sd_browser import SdBrowser
        self.stop()                      # the phone is switched off while the card is edited
        browser = SdBrowser(self, path)
        browser.run()
        browser.destroy()
        self.restart_plain()

    def sd_create(self):
        import sd_card
        dialog = Gtk.Dialog(title='Nuova scheda microSD', transient_for=self, modal=True)
        dialog.add_buttons('Annulla', Gtk.ResponseType.CANCEL, 'Crea e inserisci', Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        dialog.get_content_area().add(grid)
        size = Gtk.ComboBoxText()
        for mb in (64, 128, 256, 512, 1024, 2048):
            size.append_text(f'{mb} MB')
        size.set_active(3)
        label = Gtk.Entry(text='U310SD')
        for row, (name, widget) in enumerate((('Capacità', size), ('Nome (etichetta)', label))):
            grid.attach(Gtk.Label(label=name, xalign=0), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        dialog.show_all()
        accepted = dialog.run() == Gtk.ResponseType.OK
        megabytes, name = int(size.get_active_text().split()[0]), label.get_text()
        dialog.destroy()
        if not accepted:
            return
        path = self.choose('Dove salvare l\'immagine della scheda', Gtk.FileChooserAction.SAVE, 'Salva', save_name='microsd.img')
        if not path:
            return
        try:
            sd_card.create_image(path, megabytes, name)
        except (ValueError, OSError) as exc:
            self.message(Gtk.MessageType.ERROR, 'Creazione non riuscita', str(exc))
            return
        self.sd_set(path)

    def sd_insert(self):
        import sd_card
        path = self.choose('Immagine della scheda microSD', Gtk.FileChooserAction.OPEN, 'Inserisci')
        if not path:
            return
        try:
            sd_card.info(path)
        except (ValueError, OSError) as exc:
            self.message(Gtk.MessageType.ERROR, 'Immagine non valida', str(exc))
            return
        self.sd_set(path)

    def sd_eject(self):
        if not self.sd_current():
            self.message(Gtk.MessageType.INFO, 'Nessuna scheda inserita')
            return
        self.sd_set('')

    def with_card(self, action):
        import sd_card
        path = self.sd_current()
        if not path:
            self.message(Gtk.MessageType.INFO, 'Nessuna scheda inserita', 'Usa microSD > Crea nuova scheda… o Inserisci immagine….')
            return None
        self.stop()                      # the card must not change under a running phone
        try:
            return action(sd_card, path)
        except (ValueError, OSError) as exc:
            self.message(Gtk.MessageType.ERROR, 'Operazione non riuscita', str(exc))
        finally:
            self.restart_plain()

    def sd_format(self):
        if self.sd_current() and self.confirm('Formattare la scheda?', 'Tutti i file nella scheda verranno cancellati.'):
            self.with_card(lambda sd, path: sd.format_image(path, sd.info(path)['label'] or 'U310SD'))

    def sd_copy_in(self):
        files = self.choose('File da copiare nella scheda', Gtk.FileChooserAction.OPEN, 'Copia', multiple=True)
        if files:
            self.with_card(lambda sd, path: sd.copy_in(path, files))

    def sd_copy_out(self):
        folder = self.choose('Cartella di destinazione', Gtk.FileChooserAction.SELECT_FOLDER, 'Copia qui')
        if folder:
            self.with_card(lambda sd, path: sd.copy_out(path, folder))

    def sd_info(self):
        import sd_card
        path = self.sd_current()
        if not path:
            self.message(Gtk.MessageType.INFO, 'Nessuna scheda inserita')
            return
        data = sd_card.info(path)
        self.message(Gtk.MessageType.INFO, f'microSD {data["size_mb"]} MB, {data["fs"]}',
                     f'Nome: {data["label"]}\nFile: {path}\n\nNota: il lettore di schede del telefono non è ancora emulato, '
                     'quindi il telefono per ora non la vede.')

    def restart(self):
        self.stop()
        self.resume = None
        self.status.set_text('Riavvio con le nuove impostazioni…')
        self.start()

    def make_button(self, name, text, style):
        button = Gtk.Button(label=text)
        button.get_style_context().add_class(style)
        button.set_can_focus(False)
        button.connect('pressed', self.on_key, name, True)
        button.connect('released', self.on_key, name, False)
        return button

    def start(self):
        if not self.resume and not provision.installed():
            return self.install_wizard()
        live = self.work / 'live'
        live.mkdir(exist_ok=True)
        self.signal_file.write_text(str(self.signal_levels.get(self.settings.get('signal'), 65)))
        for name in ('main.ppm', 'sub.ppm'):
            (live / name).unlink(missing_ok=True)
        args = [sys.executable, str(ROOT / 'tools/emulator.py'), '--target', 'amss', '--nand', '--lcd-bus',
                '--shadow-mmio', '--register-banks', '--timer-irq', '--mmc-clock',
                '--mdsp-management', '--keypad', '--uim-card', '--fast', '--realtime', '--audio', '--rf-defaults', '--netsim', '--cpu-mhz', str(self.cpu_mhz),
                '--keys-file', str(self.keys_file), '--live-dir', str(live),
                '--rssi', str(self.signal_levels.get(self.settings.get('signal'), 65)), '--signal-file', str(self.signal_file), '--headset-file', str(self.headset_file),
                *(['--resume', str(self.resume)] if self.resume else ['--nand-from-checkpoint', str(NAND_IMAGE)]),
                '--imei', self.settings['imei'], '--sim', self.settings['sim'],
                *(['--sd', self.settings['sd_image']] if self.settings.get('sd_image') and Path(self.settings['sd_image']).exists() else []),
                '--bt-addr', self.settings['bt_addr'],
                *([] if self.resume else ['--save-nand', str(NAND_IMAGE), '--save-nand-after', str(BOOT_DONE)]),
                '--limit', str(10**12)]
        if self.flip_open:
            args += ['--flip', 'open']
        env = dict(os.environ, U310_PIN='off' if self.no_pin else 'on', U310_HEARTBEAT='30')
        self.child = subprocess.Popen(args, cwd=ROOT, stdout=self.log, stderr=self.log, env=env)

    def stop(self):
        if self.child and self.child.poll() is None:
            self.child.terminate()  # l'emulatore salva la flash prima di uscire
            try:
                self.child.wait(timeout=40)
            except subprocess.TimeoutExpired:
                self.child.kill()

    def on_flip(self, button):
        self.flip_open = button.get_active()
        self.stop()
        self.start()

    def write_keys(self):
        items = [f'{r},{c}' for r, c in sorted(self.held)] + (['P'] if self.power else [])
        self.keys_file.write_text(' '.join(items))

    def on_key(self, _widget, name, down):
        if name == POWER:
            self.power = down
        elif name in KEYS:
            (self.held.add if down else self.held.discard)(KEYS[name])
        self.write_keys()

    def on_pc_key(self, _window, event, down):
        name = PC_KEYS.get(event.keyval) or PC_KEYS.get(Gdk.keyval_to_lower(event.keyval))
        if name:
            pressed = self.power if name == POWER else KEYS.get(name) in self.held
            if pressed != down:
                self.on_key(None, name, down)
        return True

    def show(self, name, image, scale):
        path = self.work / 'live' / name
        if path.exists():
            try:
                frame = GdkPixbuf.Pixbuf.new_from_file(str(path))
                image.set_from_pixbuf(frame.scale_simple(frame.get_width() * scale, frame.get_height() * scale,
                                                         GdkPixbuf.InterpType.HYPER))
            except GLib.Error:
                pass  # il processo sta esportando il fotogramma successivo

    def poll(self):
        if self.closed:
            return False
        self.show('main.ppm', self.main, self.scale)
        self.show('sub.ppm', self.sub, 1)
        code = self.child.poll()
        if code is not None:
            self.status.set_text('Esecuzione fermata: vedere analysis/window.log')
        elif (self.work / 'live' / 'main.ppm').exists():
            self.status.set_text('Firmware in esecuzione')
        return True

    def close(self, *args):
        self.closed = True
        self.stop()
        self.log.close()
        Gtk.main_quit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path, help='Riprende da un checkpoint invece di avviare da zero')
    parser.add_argument('--flip-closed', action='store_true', help='Parte con il flip chiuso')
    parser.add_argument('--pin', action='store_true', help='USIM con PIN abilitato (default: PIN disabilitato)')
    parser.add_argument('--cpu-mhz', type=float, default=45.0, help='Clock emulato (istruzioni al secondo emulato). Più alto = fedele ma più lento')
    parser.add_argument('--scale', type=int, help='Ingrandimento del display principale (1-3)')
    args = parser.parse_args()
    window = EmulatorWindow(args.resume, not args.flip_closed, no_pin=not args.pin, cpu_mhz=args.cpu_mhz, scale=args.scale)
    import signal
    for signum in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, window.close)  # spegne il telefono salvando la flash
    Gtk.main()
