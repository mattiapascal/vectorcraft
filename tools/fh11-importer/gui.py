"""Small desktop front end; all conversion runs outside the UI thread."""
from pathlib import Path
import os
import queue
import subprocess
import threading
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from freehand_bridge import ROOT, VECTORCRAFT, convert
from platform_support import cli_from_selection, open_folder, user_settings_root, vectorcraft_open_command


def main():
    window = tk.Tk()
    window.title('FreeHand Importer - prototipo personale')
    window.geometry('740x430')
    window.minsize(640, 430)
    frame = ttk.Frame(window, padding=22)
    frame.pack(fill='both', expand=True)
    source = tk.StringVar()
    parent = tk.StringVar(value=str(Path.home() / 'FreeHand Importer/output'))
    target = tk.StringVar(value='VectorCraft')
    fixed_lines = tk.BooleanVar(value=False)
    status = tk.StringVar(value='Seleziona un documento FreeHand.')
    messages = queue.Queue()
    state = {'busy': False, 'output': None, 'cli': VECTORCRAFT}

    def choose_source():
        selected = filedialog.askopenfilename(title='Apri documento FreeHand', filetypes=[
            ('Documenti FreeHand', '*.fh *.fh3 *.fh4 *.fh5 *.fh6 *.fh7 *.fh8 *.fh9 *.fh10 *.fh11 *.fhmx'),
            ('Tutti i file', '*.*')])
        if selected:
            source.set(selected)

    def choose_parent():
        selected = filedialog.askdirectory(title='Cartella per i documenti importati')
        if selected:
            parent.set(selected)

    for row, label, value, chooser in [(0, 'File FreeHand', source, choose_source),
                                      (1, 'Salva in', parent, choose_parent)]:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', pady=8)
        ttk.Entry(frame, textvariable=value).grid(row=row, column=1, sticky='ew', padx=10)
        ttk.Button(frame, text='Sfoglia...', command=chooser).grid(row=row, column=2)
    frame.columnconfigure(1, weight=1)
    ttk.Label(frame, text='Destinazione').grid(row=2, column=0, sticky='w', pady=8)
    ttk.Combobox(frame, textvariable=target, state='readonly', values=[
        'VectorCraft', 'Illustrator (AI compatibile PDF)', 'Solo SVG']).grid(row=2, column=1, sticky='w', padx=10)
    ttk.Label(frame, text='Prototipo: recupera le definizioni pagina disponibili nel documento.\n'
              'Verificare pagine, testi, font, colori ed effetti rispetto a FreeHand.',
              wraplength=650).grid(row=3, column=0, columnspan=3, sticky='w', pady=16)
    ttk.Checkbutton(frame, text='Separa le righe in oggetti di testo singoli', variable=fixed_lines).grid(row=4, column=0, columnspan=3, sticky='w', pady=8)
    ttk.Label(frame, textvariable=status, wraplength=650).grid(row=6, column=0, columnspan=3, sticky='w', pady=12)

    def start():
        if state['busy']:
            return
        src = Path(source.get())
        if not src.is_file():
            messagebox.showerror('File mancante', 'Seleziona un documento FreeHand esistente.')
            return
        dest = Path(parent.get()) / (src.stem + '-importato')
        n = 2
        while dest.exists():
            dest = Path(parent.get()) / (src.stem + f'-importato-{n}')
            n += 1
        chosen = target.get()
        if chosen != 'Solo SVG' and not state['cli'].is_file():
            if sys.platform == 'darwin':
                messagebox.showinfo('Indica VectorCraft',
                                    'Seleziona VectorCraft.app nella cartella Applicazioni.')
                selected = filedialog.askopenfilename(title='Indica VectorCraft.app',
                                                     initialdir='/Applications', filetypes=[('Applicazioni', '*.app')])
            else:
                messagebox.showinfo('Indica VectorCraft',
                                    'Non trovo VectorCraft su questo PC. Seleziona vectorcraft.exe nella sua cartella di installazione.')
                selected = filedialog.askopenfilename(title='Indica VectorCraft su questo PC', filetypes=[
                    ('VectorCraft', 'vectorcraft.exe vectorcraft-cli.exe'), ('Programmi', '*.exe')])
            if not selected:
                return
            candidate = cli_from_selection(selected)
            if not candidate.is_file():
                messagebox.showerror('VectorCraft non trovato', 'La posizione selezionata non contiene la CLI di VectorCraft.')
                return
            state['cli'] = candidate
            setting = user_settings_root() / 'vectorcraft-path.txt'
            setting.parent.mkdir(parents=True, exist_ok=True)
            setting.write_text(str(candidate), encoding='utf-8')
        preserve_layout = True if fixed_lines.get() else None
        state['busy'] = True
        import_button.config(state='disabled')
        open_button.config(state='disabled')
        vectorcraft_button.config(state='disabled')
        status.set('Importazione in corso...')

        def worker():
            try:
                convert(src, dest, cli=state['cli'], native=chosen != 'Solo SVG', ai=chosen.startswith('Illustrator'), preserve_original_lines=preserve_layout)
                messages.put((dest, None))
            except Exception as error:
                messages.put((None, str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        try:
            dest, error = messages.get_nowait()
        except queue.Empty:
            window.after(150, poll)
            return
        state['busy'] = False
        import_button.config(state='normal')
        if error:
            status.set('Importazione fallita.')
            messagebox.showerror('Errore di importazione', error)
        else:
            state['output'] = dest
            status.set('Creato: ' + str(dest))
            open_button.config(state='normal')
            vectorcraft_button.config(state='normal' if (dest / 'documento.vectorcraft').is_file() else 'disabled')
        window.after(150, poll)

    def open_result():
        open_folder(state['output'])

    def open_vectorcraft():
        try:
            command = vectorcraft_open_command(state['cli'], state['output'] / 'documento.vectorcraft')
        except FileNotFoundError as error:
            messagebox.showerror('VectorCraft non trovato', str(error))
            return
        subprocess.Popen(command,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    import_button = ttk.Button(frame, text='Importa FreeHand', command=start)
    import_button.grid(row=5, column=1, sticky='w', padx=10)
    open_button = ttk.Button(frame, text='Apri cartella risultato', state='disabled', command=open_result)
    open_button.grid(row=5, column=2)
    vectorcraft_button = ttk.Button(frame, text='Apri in VectorCraft', state='disabled', command=open_vectorcraft)
    vectorcraft_button.grid(row=7, column=1, sticky='w', padx=10)

    def close():
        if state['busy']:
            messagebox.showinfo('Importazione in corso', 'Attendi la fine della conversione prima di chiudere.')
            return
        window.destroy()
    window.protocol('WM_DELETE_WINDOW', close)
    window.after(150, poll)
    window.mainloop()


if __name__ == '__main__':
    main()
