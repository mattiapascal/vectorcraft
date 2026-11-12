"""Local FreeHand conversion shared by VectorCraft and Illustrator.

All original files are read-only; output is committed as a new directory.
"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
import uuid
import xml.etree.ElementTree as ET
from source_layout import read_layout
from text_layout import restore_text
from fixed_lines import preserve_lines
from platform_support import application_root, extractor_candidates, user_settings_root, vectorcraft_candidates

ROOT = application_root()


def find_vectorcraft_cli():
    candidates = vectorcraft_candidates(ROOT)
    return next((p for p in candidates if p.is_file()), candidates[-1])


def find_extractor():
    candidates = extractor_candidates(ROOT)
    return next((p for p in candidates if p.is_file()), candidates[0])


VECTORCRAFT = find_vectorcraft_cli()
LIMIT = 512 * 1024 * 1024


class ImportFailure(RuntimeError):
    pass


@contextmanager
def work_directory(parent, prefix):
    # Inherit the workspace ACL. Python 3.13's private tempfile ACL excludes
    # the Windows sandbox identity used by this development session.
    parent = Path(parent).resolve()
    folder = parent / (prefix + uuid.uuid4().hex)
    folder.mkdir()
    try:
        yield folder
    finally:
        if folder.resolve().parent != parent or folder.is_symlink():
            raise ImportFailure('Percorso di lavoro cambiato durante la conversione.')
        shutil.rmtree(folder)


def runtime_env():
    env = os.environ.copy()
    if sys.platform == 'win32':
        env['PATH'] = str(ROOT / '.runtime/ucrt64/bin') + os.pathsep + env.get('PATH', '')
    return env


def local_work_root():
    # Keep input copies and transient parser output off a shared installation.
    # mkdir inherits normal user ACLs (unlike Python 3.13 mkdtemp's private ACL).
    parent = (Path.home() / 'Library/Caches/FreeHandImporter/Temp' if sys.platform == 'darwin'
              else user_settings_root() / 'Temp')
    parent.mkdir(parents=True, exist_ok=True)
    return parent


def commit_result(folder, destination):
    # Windows indexers/antivirus may briefly hold freshly exported AI files.
    for attempt in range(21):
        try:
            folder.rename(destination)
            return
        except PermissionError:
            if attempt == 20 or destination.exists():
                raise
            time.sleep(.25)


def identify_format(data):
    """Locate the AGD payload at a record boundary, as libfreehand does."""
    offset = 0
    while offset + 4 <= len(data):
        signature = data[offset:offset + 4]
        if signature[:3] == b'AGD' and signature[3:4] in b'123456':
            return {'signature': signature.decode('ascii'), 'offset': offset,
                    'freehandMX': signature == b'AGD6', 'creatorPatchVersion': None}
        if signature[:3] == b'FH3':
            return {'signature': signature.decode('ascii', 'replace'), 'offset': offset,
                    'freehandMX': False, 'creatorPatchVersion': None}
        if offset + 5 > len(data) or data[offset] != 0x1c:
            break
        opcode = int.from_bytes(data[offset + 1:offset + 3], 'big')
        flag, length = data[offset + 3:offset + 5]
        offset += 5
        if flag == 0x80:
            if length != 4 or offset + 4 > len(data):
                break
            length = int.from_bytes(data[offset:offset + 4], 'big')
            offset += 4
            if opcode == 0x080a:
                # Inspect only the beginning of this payload, never arbitrary bytes.
                header = data[offset:offset + 4]
                if len(header) == 4 and header[:3] == b'AGD' and header[3:4] in b'123456':
                    return {'signature': header.decode('ascii'), 'offset': offset,
                            'freehandMX': header == b'AGD6', 'creatorPatchVersion': None}
        offset += length
    return {'signature': None, 'freehandMX': None, 'creatorPatchVersion': None}


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, timeout=180,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **kwargs)
    if result.returncode:
        error = result.stderr.decode('utf-8', 'replace').strip()
        raise ImportFailure(error or f'Il processo ha restituito {result.returncode}.')
    return result


def read_pages(data):
    """Read the extractor's length-framed UTF-8 SVGs, rejecting truncated output."""
    if len(data) > LIMIT:
        raise ImportFailure('Documento convertito superiore al limite di 512 MiB.')
    stream = io.BytesIO(data)
    if stream.readline() != b'FHI1\n':
        raise ImportFailure('Risposta non valida dal motore FreeHand.')
    try:
        count = int(stream.readline())
        if not 1 <= count <= 10000:
            raise ValueError('numero pagine fuori limite')
        pages = []
        for _ in range(count):
            length = int(stream.readline())
            if not 0 < length <= LIMIT:
                raise ValueError('lunghezza SVG fuori limite')
            svg = stream.read(length)
            if len(svg) != length:
                raise ValueError('SVG incompleto')
            element = ET.fromstring(svg)
            if element.tag != '{http://www.w3.org/2000/svg}svg':
                raise ValueError('radice SVG non valida')
            pages.append(svg)
        if stream.read(1):
            raise ValueError('dati residui')
        return pages
    except (ValueError, ET.ParseError) as error:
        raise ImportFailure(f'Output del parser incompleto o non valido: {error}') from error


def point_length(value):
    match = re.fullmatch(r'\s*([+\-\d.eE]+)\s*(pt|pc|in|cm|mm|px)?\s*', value or '')
    if not match:
        raise ImportFailure('Dimensioni SVG non interpretabili: ' + str(value))
    scale = {'pt': 1, 'pc': 12, 'in': 72, 'cm': 72 / 2.54, 'mm': 72 / 25.4, 'px': .75, None: .75}
    number = float(match[1]) * scale[match[2]]
    if not math.isfinite(number) or number <= 0:
        raise ImportFailure('Dimensioni SVG non valide.')
    return number


def read_page_records(diagnostics):
    records, origins = [], []
    try:
        for line in diagnostics.decode('utf-8', 'replace').split('\n'):
            parts = line.split()
            if parts and parts[0] == 'FHPAGE':
                if len(parts) != 6:
                    raise ValueError('record pagina incompleto')
                record = int(parts[1])
                x, y, width, height = map(float, parts[2:])
                if not all(math.isfinite(v) for v in [x, y, width, height]) or width <= 0 or height <= 0:
                    raise ValueError('dimensioni pagina non valide')
                records.append((record, x, y, width, height))
            elif parts and parts[0] == 'FHORIGIN':
                origins.append(tuple(map(float, parts[1:])))
        if not records:
            return []
        if len(origins) != 1 or len(origins[0]) != 2 or len(records) > 10000:
            raise ValueError('origine del disegno non univoca')
        ox, oy = origins[0]
        result, seen = [], set()
        for record, x, y, width, height in records:
            rect = [72 * (x - ox), 72 * (oy - y - height), 72 * width, 72 * height]
            if not all(math.isfinite(v) and abs(v) <= 4000000 for v in rect):
                raise ValueError('pagina fuori dai limiti di VectorCraft')
            key = tuple(round(v, 6) for v in rect)
            if key not in seen:
                result.append({'recordId': record, 'rect': rect})
                seen.add(key)
        return result
    except (ValueError, OverflowError) as error:
        raise ImportFailure(f'Metadati delle pagine non validi: {error}') from error


def vectorcraft_document(folder, pages, cli, ai, final_folder=None, source_artboards=None,
                         source_text_records=None, preserve_original_lines=None):
    if not cli.is_file():
        raise ImportFailure(f'CLI VectorCraft non trovata: {cli}')
    commands = []
    x = 0
    for index, page in enumerate(pages):
        svg = ET.fromstring(page)
        width, height = point_length(svg.get('width')), point_length(svg.get('height'))
        path = str(folder / f'pagina-{index + 1:03}.svg')
        if index == 0:
            commands.append({'command': 'document.open', 'params': {'path': path}})
            commands.append({'command': 'artboard.setProps', 'params': {'index': 0, 'name': 'Pagina 1'}})
        else:
            commands.append({'command': 'artboard.new', 'params': {
                'x': x, 'y': 0, 'width': width, 'height': height, 'name': f'Pagina {index + 1}'}})
            commands.append({'command': 'file.place', 'params': {
                'path': path, 'link': False, 'crop': 'crop', 'at': [x + width / 2, height / 2]}})
        x += width + 36
    if source_artboards:
        if len(pages) != 1:
            raise ImportFailure('Impossibile associare le definizioni pagina a piu superfici SVG.')
        # Add the recovered artboards, then remove the generated canvas. Changing
        # that canvas with setProps could move its artwork, which must stay put.
        for index, entry in enumerate(source_artboards, 1):
            px, py, pw, ph = entry['rect']
            commands.append({'command': 'artboard.new', 'params': {
                'x': px, 'y': py, 'width': pw, 'height': ph, 'name': f'Pagina {index}'}})
        commands.append({'command': 'artboard.delete', 'params': {'index': 0}})
    commands.append({'command': 'document.save', 'params': {'path': str(folder / 'documento.vectorcraft'), 'compress': False}})
    exports = []
    if ai:
        # libfreehand currently emits one surface; original pasteboard art can
        # lie outside it. For that case export all visible art, avoiding cropping.
        exports.append({'command': 'document.export', 'params': {
            'path': str(folder / 'documento.ai'), 'format': 'ai',
            'useArtboards': bool(source_artboards) or len(pages) > 1}})
        if source_artboards:
            exports.append({'command': 'document.export', 'params': {
                'path': str(folder / 'documento-completo.ai'), 'format': 'ai', 'useArtboards': False}})
    script = folder / 'vectorcraft-commands.json'
    script.write_text(json.dumps(commands, ensure_ascii=False), encoding='utf-8')
    result = run([str(cli), 'run', '--commands', str(script)])
    log = result.stdout.decode('utf-8', 'replace')
    text_report = None
    if source_text_records:
        native_path = folder / 'documento.vectorcraft'
        text_report = restore_text(native_path, source_text_records, keep_saved_breaks=preserve_original_lines is None)
        if preserve_original_lines:
            line_report = preserve_lines(native_path, source_text_records)
            (folder / 'source-text-boxes.json').write_text(json.dumps(line_report, ensure_ascii=False, indent=2), encoding='utf-8')
            text_report['originalLineLayout'] = {k: v for k, v in line_report.items() if k != 'boxes'}
    if exports:
        script.write_text(json.dumps(exports, ensure_ascii=False), encoding='utf-8')
        exported = run([str(cli), 'run', '--in', str(folder / 'documento.vectorcraft'), '--commands', str(script)])
        log += exported.stdout.decode('utf-8', 'replace')
    (folder / 'vectorcraft-log.jsonl').write_text(log, encoding='utf-8')
    if not (folder / 'documento.vectorcraft').is_file():
        raise ImportFailure('VectorCraft non ha creato il documento.')
    info = run([str(cli), 'info', str(folder / 'documento.vectorcraft')])
    details = json.loads(info.stdout)
    if text_report is not None:
        details['textLayoutRepair'] = text_report
    details['conversionSteps'] = [json.loads(line) for line in log.splitlines() if line.strip()]
    details['file'] = str((final_folder or folder) / 'documento.vectorcraft')
    (folder / 'vectorcraft-info.json').write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding='utf-8')
    expected = len(source_artboards) if source_artboards else len(pages)
    if len(details.get('artboards', [])) != expected:
        raise ImportFailure('Il numero di tavole VectorCraft non coincide con le pagine estratte.')
    # The staged absolute paths are only needed while the CLI is running.
    script.unlink()
    return details


def convert(source, destination, cli=VECTORCRAFT, native=True, ai=False, preserve_original_lines=None):
    # None preserves saved breaks in a single frame. True splits the rows;
    # False leaves automatic wrapping to the destination application.
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ImportFailure(f'File non trovato: {source}')
    if destination.exists():
        raise ImportFailure(f'La cartella di destinazione esiste gia: {destination}')
    if source.stat().st_size > LIMIT:
        raise ImportFailure('File superiore al limite di 512 MiB.')
    extractor = find_extractor()
    if not extractor.is_file():
        raise ImportFailure('Motore FreeHand non trovato nel pacchetto. Ricreare o ricopiare il pacchetto completo.')
    # A plain ASCII basename also handles original paths outside the Windows code page.
    with work_directory(local_work_root(), 'freehand-') as temporary:
        staged = Path(temporary) / 'input.fh'
        shutil.copyfile(source, staged)
        original = staged.read_bytes()
        source_hash = hashlib.sha256(original).hexdigest()
        source_format = identify_format(original)
        del original
        response = run([str(extractor), 'input.fh'], cwd=temporary, env=runtime_env())
    pages = read_pages(response.stdout)
    source_artboards = read_page_records(response.stderr)
    source_text_records = read_layout(response.stderr)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with work_directory(destination.parent, '.freehand-') as temporary:
        folder = Path(temporary) / 'result'
        folder.mkdir()
        for index, svg in enumerate(pages, 1):
            (folder / f'pagina-{index:03}.svg').write_bytes(svg)
        if source_text_records:
            (folder / 'source-text-layout.json').write_text(json.dumps(source_text_records, ensure_ascii=False, indent=2), encoding='utf-8')
        report = {
            'source': str(source), 'sourceSha256': source_hash,
            'parser': 'libfreehand 0.1.3 + librevenge', 'pages': len(pages),
            'parserVariant': 'page-metadata' if extractor.name.startswith('fh_extract_pages') else 'standard',
            'sourceFormat': source_format,
            'recoveredPageDefinitions': source_artboards,
            'recoveredPageCount': len(source_artboards) if source_artboards else None,
            'originalPageCount': None, 'originalPageStructureVerified': False,
            'textEditingMode': {None: 'area-text-with-saved-lines', True: 'grouped-original-lines',
                                False: 'reflowable-area-text'}[preserve_original_lines] if native else 'raw-svg-text',
            'aiExportScope': ('recovered-page-definitions' if source_artboards else
                              'all-visible-artwork' if len(pages) == 1 else 'generated-surfaces') if ai else None,
            'fidelityVerified': False,
            'limitations': [
                'pages indica gli SVG prodotti; recoveredPageCount indica le definizioni pagina recuperate, ancora da confrontare con FreeHand.',
                'La riuscita del parser non certifica la fedelta rispetto a FreeHand.',
                'Controllare testi, font, colori CMYK e tinte piatte, sfumature, effetti, immagini e livelli.',
                'Risorse collegate esterne e resource fork Macintosh non sono recuperati automaticamente.',
                'La via SVG non conserva tutte le strutture di modifica native di FreeHand.',
                'Le pagine successive sono inserite con ritaglio ai limiti pagina; verificare gli oggetti esterni.',
            ],
            'parserStderr': '\n'.join(line for line in response.stderr.decode('utf-8', 'replace').split('\n')
                                      if not line.startswith(('FHTEXT ', 'FHLINEROW ', 'FHLINEREF '))),
        }
        if native:
            report['vectorcraft'] = vectorcraft_document(folder, pages, Path(cli), ai, destination, source_artboards,
                                                         source_text_records, preserve_original_lines)
        (folder / 'rapporto.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        commit_result(folder, destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description='Converte FreeHand in SVG e VectorCraft; struttura pagine originale non verificata.')
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', type=Path, required=True, help='Nuova cartella di destinazione')
    parser.add_argument('--svg-only', action='store_true')
    parser.add_argument('--ai', action='store_true', help='Esporta anche AI compatibile PDF tramite VectorCraft')
    text_mode = parser.add_mutually_exclusive_group()
    text_mode.add_argument('--reflow-text', dest='separate_lines', action='store_false', default=None,
                           help='Ricalcola gli a capo automatici nelle caselle originali')
    text_mode.add_argument('--separate-lines', action='store_true', help='Rendi modificabile ogni riga come oggetto separato')
    parser.add_argument('--vectorcraft-cli', type=Path, default=VECTORCRAFT)
    args = parser.parse_args()
    if args.ai and args.svg_only:
        parser.error('--ai richiede VectorCraft; rimuovere --svg-only')
    try:
        print(convert(args.source, args.out, args.vectorcraft_cli, not args.svg_only, args.ai, args.separate_lines))
    except (ImportFailure, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        parser.exit(1, f'Importazione fallita: {error}\n')


if __name__ == '__main__':
    main()
