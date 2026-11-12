"""Paths and desktop commands shared by Windows and macOS builds."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile


def application_root():
    if not getattr(sys, 'frozen', False):
        return Path(__file__).resolve().parent
    executable = Path(sys.executable).resolve()
    if sys.platform == 'darwin' and executable.parent.name == 'MacOS':
        return executable.parents[3]  # folder containing the .app
    return executable.parent


def user_settings_root():
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/FreeHandImporter'
    return Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'FreeHandImporter'


def cli_from_selection(selection):
    selected = Path(selection)
    if sys.platform == 'darwin':
        if selected.suffix.lower() == '.app':
            return selected / 'Contents/MacOS/vectorcraft-cli'
        if selected.name == 'vectorcraft-cli':
            return selected
        return selected.parent / 'vectorcraft-cli'
    return selected.parent / 'vectorcraft-cli.exe'


def vectorcraft_candidates(root):
    candidates = []
    if os.environ.get('FREEHAND_VECTORCRAFT_CLI'):
        candidates.append(cli_from_selection(os.environ['FREEHAND_VECTORCRAFT_CLI']))
    for setting in (root / 'vectorcraft-path.txt', user_settings_root() / 'vectorcraft-path.txt'):
        if setting.is_file():
            value = setting.read_text(encoding='utf-8-sig').strip().strip('"')
            if value:
                path = Path(value)
                candidates.append(cli_from_selection(path if path.is_absolute() else root / path))
    if sys.platform == 'darwin' and getattr(sys, 'frozen', False):
        candidates.append(Path(sys._MEIPASS) / 'vectorcraft/vectorcraft-cli')
    name = 'vectorcraft-cli' if sys.platform == 'darwin' else 'vectorcraft-cli.exe'
    if shutil.which(name):
        candidates.append(Path(shutil.which(name)))
    if sys.platform == 'darwin':
        candidates += [Path('/Applications/VectorCraft.app/Contents/MacOS/vectorcraft-cli'),
                       Path.home() / 'Applications/VectorCraft.app/Contents/MacOS/vectorcraft-cli',
                       Path('/opt/homebrew/bin/vectorcraft-cli'),
                       Path('/usr/local/bin/vectorcraft-cli'),
                       Path(getattr(sys, '_MEIPASS', root)) / 'vectorcraft/vectorcraft-cli']
    else:
        for base in (os.environ.get('ProgramFiles', r'C:\Program Files'),
                     os.environ.get('ProgramW6432', r'C:\Program Files'),
                     str(Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'Programs')):
            candidates.append(Path(base) / 'VectorCraft/vectorcraft-cli.exe')
    return candidates


def extractor_candidates(root):
    if sys.platform == 'darwin':
        resources = Path(getattr(sys, '_MEIPASS', root))
        return [resources / 'native/fh_extract_pages', root / 'build/fh_extract_pages']
    return [root / 'build/fh_extract_pages.exe', root / 'build/fh_extract.exe']


def desktop_open_command(path):
    if sys.platform == 'darwin':
        return ['/usr/bin/open', str(path)]
    return None


def vectorcraft_open_command(cli, document):
    cli = Path(cli)
    if sys.platform == 'darwin':
        bundle = next((parent for parent in cli.parents if parent.name.lower() == 'vectorcraft.app'), None)
        if bundle is None:
            bundle = next((p for p in (Path('/Applications/VectorCraft.app'), Path.home() / 'Applications/VectorCraft.app') if p.is_dir()), None)
        if bundle:
            return ['/usr/bin/open', '-a', str(bundle), str(document)]
        if getattr(sys, 'frozen', False) and cli.is_relative_to(Path(getattr(sys, '_MEIPASS', '/not-a-bundle'))):
            raise FileNotFoundError('Per visualizzare il risultato installa VectorCraft.app nella cartella Applicazioni. La conversione e gia completata.')
        executable = cli.parent / 'vectorcraft'
    else:
        executable = cli.parent / 'vectorcraft.exe'
    if not executable.is_file():
        raise FileNotFoundError('Non trovo VectorCraft accanto alla CLI selezionata.')
    return [str(executable), str(document)]


def open_folder(path):
    command = desktop_open_command(path)
    if command:
        subprocess.Popen(command)
    else:
        os.startfile(path)
