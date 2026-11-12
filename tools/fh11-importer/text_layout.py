"""Restore editable text boxes and paragraph boundaries captured before SVG."""
from pathlib import Path
import copy
import json
import math
import re
import sys
from source_layout import uniform_leading


def read_native(path):
    raw = Path(path).read_bytes()
    text = raw.decode('utf-8', 'replace')
    document, end = json.JSONDecoder().raw_decode(text)
    # Native v4 may append binary image blobs after its UTF-8 JSON prefix.
    offset = len(text[:end].encode('utf-8'))
    return document, raw[offset:]


def write_native(path, document, tail):
    Path(path).write_bytes(json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8') + tail)


def text_nodes(document):
    result = []
    def visit(value):
        if isinstance(value, dict):
            if isinstance(value.get('kind'), dict) and value['kind'].get('type') == 'text':
                result.append(value)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(document['document']['layers'])
    return sorted(result, key=lambda item: item['id'])


def number(value, default=0):
    match = re.fullmatch(r'\s*([-+\d.eE]+)(pt|in|mm|cm|%)?\s*', str(value))
    if not match:
        return default
    result = float(match[1]) * {'in': 72, 'pt': 1, 'mm': 72/25.4, 'cm': 72/2.54, '%': 1, None: 1}[match[2]]
    if not math.isfinite(result):
        raise ValueError('Non-finite text property')
    return result


def source_text(record):
    return '\n'.join(''.join(span['text'] for span in para['spans']) for para in record['paragraphs'])


def units(value):
    return len(value.encode('utf-16-le')) // 2


def slice_runs(runs, start, end):
    result, cursor = [], 0
    for run in runs:
        encoded = run['text'].encode('utf-16-le')
        length = len(encoded) // 2
        a, b = max(start, cursor), min(end, cursor + length)
        if a < b:
            text = encoded[2*(a-cursor):2*(b-cursor)].decode('utf-16-le')
            result.append({'text': text, 'style': copy.deepcopy(run['style'])})
        cursor += length
        if cursor >= end:
            break
    return result


def saved_line_runs(runs, rows):
    """Apply the saved line breaks and baseline gaps inside a single text frame."""
    if not rows:
        return None
    body = ''.join(run['text'] for run in runs)
    length = units(body)
    result, end = [], 0
    for index, row in enumerate(rows):
        start, limit = row['start'], row['start'] + row['length']
        if start != end or not start < limit <= length + (index == len(rows) - 1):
            return None
        end = min(length, limit)
        try:
            pieces = slice_runs(runs, start, end)
        except UnicodeDecodeError:
            return None
        text = ''.join(piece['text'] for piece in pieces)
        if not pieces or '\n' in text.removesuffix('\n'):
            return None
        for piece in pieces:
            piece['style']['noBreak'] = True
        if index:
            leading = rows[index - 1]['y'] - row['y']
            if 0 < leading < 10000:
                for piece in pieces:
                    piece['style']['leading'] = leading
        result.extend(pieces)
        if index + 1 < len(rows) and not text.endswith('\n'):
            result.append({'text': '\u2028', 'style': copy.deepcopy(pieces[-1]['style'])})
    return result if end == length else None


def freehand_font(family, bold, italic):
    style = 'Bold Italic' if bold and italic else 'Bold' if bold else 'Italic' if italic else 'Regular'
    if family.casefold() == 'arial narrow' and sys.platform == 'win32':
        return 'Arial', 'Narrow' + ('' if style == 'Regular' else ' ' + style)
    if family.casefold() == 'bookmanitc lt bt':
        return 'BookmanITC Lt BT', ('Demi' if bold else 'Light') + (' Italic' if italic else '')
    return family, style


def restore_text(path, records, keep_saved_breaks=False):
    document, tail = read_native(path)
    nodes = text_nodes(document)
    if len(nodes) != len(records):
        raise ValueError('Text object counts differ; refusing positional matching')
    changed, skipped, breaks, saved = 0, [], 0, 0
    for index, (node, record) in enumerate(zip(nodes, records), 1):
        if record['index'] != index:
            raise ValueError('Text capture sequence is incomplete')
        kind = node['kind']
        preserve_native = kind.get('kind', {}).get('kind') == 'area'
        before = ''.join(run['text'] for run in kind['runs'])
        original = source_text(record)
        if re.sub(r'\s', '', before) != re.sub(r'\s', '', original):
            skipped.append(index)
            continue
        base = next((r['style'] for r in kind['runs'] if r['text'].strip()), kind['runs'][0]['style'] if kind['runs'] else {})
        # Keep the resolved native font names and CMYK paints on the Tensai route.
        native_styles = [r['style'] for r in kind['runs'] for _ in r['text']] if preserve_native and before == original else []
        cursor = 0
        exact_leading = uniform_leading(record)
        runs = []
        for pi, paragraph in enumerate(record['paragraphs']):
            if pi:
                runs.append({'text': '\n', 'style': copy.deepcopy(runs[-1]['style'] if runs else base)})
                cursor += 1
            for span in paragraph['spans']:
                props = span['props']
                style = copy.deepcopy(native_styles[cursor] if cursor < len(native_styles) else base)
                bold = props.get('fo:font-weight') == 'bold'
                italic = props.get('fo:font-style') in ['italic', 'oblique']
                if not preserve_native:
                    family = props.get('style:font-name', style.get('font_family', 'Arial'))
                    style['font_family'], style['font_style'] = freehand_font(family, bold, italic)
                size = number(props.get('fo:font-size'), style.get('size', 12))
                style['size'] = size
                style['tracking'] = 1000 * number(props.get('fo:letter-spacing'), 0) / size if size else 0
                style['h_scale'] = number(props.get('style:text-scale'), 100)
                if not preserve_native:
                    style.pop('leading', None)
                leading = paragraph['props'].get('fo:line-height')
                if leading:
                    style['leading'] = size * number(leading) / 100 if leading.endswith('%') else number(leading)
                elif exact_leading:
                    style['leading'] = exact_leading
                position = props.get('style:text-position')
                style['baseline_shift'] = size * number(position.split()[0]) / 100 if position and '%' in position.split()[0] else 0
                color = props.get('fo:color')
                if not preserve_native and color and re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                    style['fill'] = {'type': 'solid', 'color': {'model': 'rgb', **{
                        c: int(color[1+i*2:3+i*2], 16)/255 for i, c in enumerate('rgb')}}}
                text = span['text'].replace('\u2028', '\n').replace('\u2029', '\n')
                runs.append({'text': text, 'style': style})
                cursor += len(span['text'])
        width = number(record['props'].get('svg:width'))
        height = number(record['props'].get('svg:height'))
        if not preserve_native and width > 0 and height > 0:
            kind['kind'] = {'kind': 'area', 'frame': {'subpaths': [{'closed': True, 'anchors': [
                {'p': [0, -height]}, {'p': [width, -height]}, {'p': [width, 0]}, {'p': [0, 0]}]}]}}
        raw_y = number(record['props'].get('fhi:raw-y', record['props'].get('fhi:raw-bottom')))
        if record.get('lines') and raw_y and kind['kind']['kind'] == 'area':
            baseline = raw_y - record['lines'][0]['y']
            if 0 <= baseline <= height:
                area = kind.setdefault('area', {'rows': 1, 'columns': 1, 'gutter': 0, 'inset': 0, 'verticalAlign': 'top'})
                area['firstBaseline'] = 'fixed'
                area['firstBaselineMin'] = baseline
        if record['paragraphs']:
            props = record['paragraphs'][0]['props']
            para = copy.deepcopy(kind.get('para', {}))
            para['justify'] = {'left': 'Left', 'center': 'Center', 'end': 'Right', 'justify': 'JustifyLeft'}.get(props.get('fo:text-align'), 'Left')
            kind['para'] = para
        if keep_saved_breaks and kind['kind']['kind'] == 'area':
            rows = record.get('lines', [])
            laid_out = saved_line_runs(runs, rows)
            if laid_out is not None:
                runs = laid_out
                saved += 1
                last_baseline = raw_y - rows[-1]['y']
                if not preserve_native and width > 0 and 0 <= last_baseline <= height:
                    # VectorCraft requires room for descenders below the last
                    # baseline. Extend the bottom edge without moving the top.
                    bottom = last_baseline + rows[-1]['size'] / 2 - height
                    if bottom > 0:
                        anchors = kind['kind']['frame']['subpaths'][0]['anchors']
                        anchors[2]['p'][1] = anchors[3]['p'][1] = bottom
                    if len(rows) == 1 and width < rows[0]['size']:
                        # The area composer needs room for the face's ascent
                        # even when a single glyph itself fits in less space.
                        extra = rows[0]['size'] - width
                        align = kind['para']['justify']
                        left = -extra / 2 if align == 'Center' else -extra if align == 'Right' else 0
                        anchors = kind['kind']['frame']['subpaths'][0]['anchors']
                        anchors[0]['p'][0] = anchors[3]['p'][0] = left
                        anchors[1]['p'][0] = anchors[2]['p'][0] = left + width + extra
        kind['runs'] = runs
        breaks += sum(run['text'].count('\n') + run['text'].count('\u2028') for run in runs)
        changed += 1
    write_native(path, document, tail)
    return {'restoredTextObjects': changed, 'skippedTextObjects': skipped, 'lineBreaks': breaks,
            'boxesWithSavedLines': saved, 'binaryImageTailBytes': len(tail)}
