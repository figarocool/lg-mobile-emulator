"""File manager window for a microSD image (Gtk). Opened from the emulator window; the phone is off meanwhile."""
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk  # noqa: E402

import sd_card  # noqa: E402


def human(size):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024


class SdBrowser(Gtk.Dialog):
    def __init__(self, parent, image):
        super().__init__(title='Esplora microSD', transient_for=parent, modal=True)
        self.image, self.folder = image, ''
        self.set_default_size(640, 460)
        self.add_button('Chiudi e riaccendi il telefono', Gtk.ResponseType.CLOSE)
        area = self.get_content_area()
        area.set_spacing(6)
        bar = Gtk.Box(spacing=4, margin=6)
        for label, handler in (('⬆ Su', self.up), ('Aggiorna', self.refresh), ('Carica file…', self.upload),
                               ('Nuova cartella…', self.new_folder), ('Rinomina…', self.rename), ('Elimina', self.remove),
                               ('Scarica…', self.download), ('Formatta / dimensione…', self.format)):
            button = Gtk.Button(label=label)
            button.connect('clicked', lambda _b, h=handler: h())
            bar.pack_start(button, False, False, 0)
        area.pack_start(bar, False, False, 0)
        self.path = Gtk.Label(xalign=0, margin_start=8)
        area.pack_start(self.path, False, False, 0)
        self.store = Gtk.ListStore(str, str, str, bool)   # name, size, kind, is_dir
        self.view = Gtk.TreeView(model=self.store)
        for index, title in enumerate(('Nome', 'Dimensione', 'Tipo')):
            column = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=index)
            column.set_resizable(True)
            column.set_expand(index == 0)
            self.view.append_column(column)
        self.view.set_headers_clickable(False)
        self.view.connect('row-activated', self.activated)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.view)
        area.pack_start(scroll, True, True, 0)
        self.status = Gtk.Label(xalign=0, margin=6)
        area.pack_start(self.status, False, False, 0)
        self.show_all()
        self.refresh()

    def error(self, exc):
        box = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                buttons=Gtk.ButtonsType.OK, text='Operazione non riuscita')
        box.format_secondary_text(str(exc))
        box.run()
        box.destroy()

    def guarded(self, action):
        try:
            action()
        except (ValueError, OSError) as exc:
            self.error(exc)
        self.refresh()

    def selected(self):
        model, row = self.view.get_selection().get_selected()
        return (model[row][0], model[row][3]) if row else (None, False)

    def refresh(self):
        self.store.clear()
        try:
            for name, is_dir, size in sd_card.entries(self.image, self.folder):
                self.store.append([name, '' if is_dir else human(size), 'Cartella' if is_dir else 'File', is_dir])
            free = sd_card.free_space(self.image)
            info = sd_card.info(self.image)
            self.status.set_text(f'{info["size_mb"]} MB {info["fs"]}, nome {info["label"]}'
                                 + (f', liberi {human(free)}' if free is not None else ''))
        except ValueError as exc:
            self.status.set_text(str(exc))
        self.path.set_text('Scheda:/' + self.folder)

    def activated(self, _view, path, _column):
        name, is_dir = self.store[path][0], self.store[path][3]
        if is_dir:
            self.folder = (self.folder + '/' + name).strip('/')
            self.refresh()

    def up(self):
        self.folder = '/'.join(self.folder.split('/')[:-1])
        self.refresh()

    def ask_text(self, title, default=''):
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dialog.add_buttons('Annulla', Gtk.ResponseType.CANCEL, 'OK', Gtk.ResponseType.OK)
        entry = Gtk.Entry(text=default, margin=10, activates_default=True)
        dialog.get_content_area().add(entry)
        dialog.show_all()
        answer = entry.get_text().strip() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        return answer

    def pick(self, title, action, accept, multiple=False):
        chooser = Gtk.FileChooserDialog(title=title, transient_for=self, action=action)
        chooser.add_buttons('Annulla', Gtk.ResponseType.CANCEL, accept, Gtk.ResponseType.OK)
        chooser.set_select_multiple(multiple)
        result = (chooser.get_filenames() if multiple else chooser.get_filename()) if chooser.run() == Gtk.ResponseType.OK else None
        chooser.destroy()
        return result

    def upload(self):
        files = self.pick('File o cartelle da caricare', Gtk.FileChooserAction.OPEN, 'Carica', multiple=True)
        if files:
            self.guarded(lambda: sd_card.upload(self.image, files, self.folder))

    def new_folder(self):
        name = self.ask_text('Nome della nuova cartella')
        if name:
            self.guarded(lambda: sd_card.make_folder(self.image, self.folder, name))

    def rename(self):
        name, _is_dir = self.selected()
        if name:
            new = self.ask_text('Nuovo nome', name)
            if new and new != name:
                self.guarded(lambda: sd_card.rename(self.image, self.folder, name, new))

    def remove(self):
        name, is_dir = self.selected()
        if not name:
            return
        box = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.YES_NO, text=f'Eliminare "{name}"?')
        answer = box.run() == Gtk.ResponseType.YES
        box.destroy()
        if answer:
            self.guarded(lambda: sd_card.delete(self.image, self.folder, name, is_dir))

    def download(self):
        name, _is_dir = self.selected()
        if name:
            destination = self.pick('Dove salvare sul PC', Gtk.FileChooserAction.SELECT_FOLDER, 'Salva qui')
            if destination:
                self.guarded(lambda: sd_card.download(self.image, self.folder, name, destination))

    def format(self):
        dialog = Gtk.Dialog(title='Formatta la scheda', transient_for=self, modal=True)
        dialog.add_buttons('Annulla', Gtk.ResponseType.CANCEL, 'Formatta (cancella tutto)', Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        dialog.get_content_area().add(grid)
        size = Gtk.ComboBoxText.new_with_entry()
        current = sd_card.info(self.image)['size_mb']
        for mb in (64, 128, 256, 512, 1024, 2048, 4096, 8192):
            size.append_text(str(mb))
        size.get_child().set_text(str(current))
        label = Gtk.Entry(text=sd_card.info(self.image)['label'] or 'U310SD')
        for row, (name, widget) in enumerate((('Capacità (MB)', size), ('Nome (etichetta)', label))):
            grid.attach(Gtk.Label(label=name, xalign=0), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        dialog.show_all()
        accepted = dialog.run() == Gtk.ResponseType.OK
        text, name = size.get_child().get_text().strip(), label.get_text()
        dialog.destroy()
        if not accepted:
            return
        try:
            megabytes = int(text)
        except ValueError:
            self.error('La capacità deve essere un numero di MB')
            return
        self.folder = ''
        self.guarded(lambda: sd_card.reformat(self.image, megabytes, name))
