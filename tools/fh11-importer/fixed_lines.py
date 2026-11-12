"""Keep FreeHand's saved line positions as grouped, individually editable lines."""
import copy
import json
from text_layout import number, read_native, slice_runs, source_text, text_nodes, units, write_native


def preserve_lines(path, records):
    document, tail = read_native(path)
    nodes = text_nodes(document)
    if len(nodes) != len(records):
        raise ValueError('Text count mismatch')
    next_id = 1
    def count_ids(value):
        nonlocal next_id
        if isinstance(value, dict):
            if isinstance(value.get('id'), int):
                next_id = max(next_id, value['id'] + 1)
            for child in value.values():
                count_ids(child)
        elif isinstance(value, list):
            for child in value:
                count_ids(child)
    count_ids(document['document']['layers'])
    converted, line_count, skipped, backups = 0, 0, [], []
    for node, record in zip(nodes, records):
        kind = node['kind']
        rows = record.get('lines', [])
        body = ''.join(run['text'] for run in kind['runs'])
        original = source_text(record).replace('\u2028', '\n').replace('\u2029', '\n')
        if kind.get('kind', {}).get('kind') != 'area' or not rows or body != original:
            skipped.append(record['index'])
            continue
        props = record['props']
        raw_x = number(props.get('fhi:raw-left'))
        raw_y = number(props.get('fhi:raw-y', props.get('fhi:raw-bottom')))
        raw_w, raw_h = number(props.get('fhi:raw-width')), number(props.get('fhi:raw-height'))
        anchors = kind['kind']['frame']['subpaths'][0]['anchors']
        if len(anchors) < 4 or raw_w <= 0 or raw_h <= 0:
            skipped.append(record['index'])
            continue
        p0, p1, p3 = anchors[0]['p'], anchors[1]['p'], anchors[3]['p']
        bx = [(p1[i]-p0[i])/raw_w for i in range(2)]
        by = [(p3[i]-p0[i])/raw_h for i in range(2)]
        xf = kind.get('xf', [1, 0, 0, 1, 0, 0])
        def point(x, y):
            lx = p0[0] + bx[0]*x + by[0]*y
            ly = p0[1] + bx[1]*x + by[1]*y
            return [xf[0]*lx + xf[2]*ly + xf[4], xf[1]*lx + xf[3]*ly + xf[5]]
        def vector(v):
            return [xf[0]*v[0] + xf[2]*v[1], xf[1]*v[0] + xf[3]*v[1]]
        ax, ay = vector(bx), vector(by)
        full = body + '\n'
        encoded = full.encode('utf-16-le')
        full_runs = copy.deepcopy(kind['runs']) + [{'text': '\n', 'style': copy.deepcopy(kind['runs'][-1]['style'])}]
        chunks = []
        invalid = False
        for row in rows:
            start, end = row['start'], row['start'] + row['length']
            if end*2 > len(encoded) or start < 0:
                invalid = True
                break
            text = encoded[start*2:end*2].decode('utf-16-le')
            # Returns are structure in the output; ordinary spaces are retained.
            while text.endswith(('\n', '\r', '\u2028', '\u2029')):
                text = text[:-1]
                end -= 1
            if any(c in text for c in ['\n', '\r', '\u2028', '\u2029']):
                invalid = True
                break
            chunks.append((row, text, slice_runs(full_runs, start, end)))
        if invalid or ''.join(c for _, text, _ in chunks for c in text if not c.isspace()) != ''.join(c for c in body if not c.isspace()):
            skipped.append(record['index'])
            continue
        children, line_plans = [], []
        paragraph_ends, pos = [], 0
        for paragraph in record['paragraphs']:
            text = ''.join(span['text'] for span in paragraph['spans'])
            pos += units(text) + 1
            paragraph_ends.append(pos)
        for row, text, runs in chunks:
            if not text.strip():
                continue
            pi = next((i for i, end in enumerate(paragraph_ends) if row['start'] < end), 0)
            align = record['paragraphs'][pi]['props'].get('fo:text-align', 'left')
            dx = row['x'] - raw_x
            if align == 'center':
                dx += row['width']/2
            elif align == 'end':
                dx += row['width']
            location = point(dx, raw_y - row['y'])
            para = copy.deepcopy(kind.get('para', {}))
            para['justify'] = {'center': 'Center', 'end': 'Right'}.get(align, 'Left')
            children.append({'id': next_id, 'kind': {
                'type': 'text', 'kind': {'kind': 'point'},
                'xf': [ax[0], ax[1], ay[0], ay[1], location[0], location[1]],
                'runs': runs, 'para': para}})
            line_plans.append({'text': text, 'sourceStart': row['start'], 'sourceLength': units(text),
                               'position': location, 'align': para['justify'],
                               'matrix': [ax[0], ax[1], ay[0], ay[1]], 'runs': runs})
            next_id += 1
        corner = [xf[0]*p0[0] + xf[2]*p0[1] + xf[4], xf[1]*p0[0] + xf[3]*p0[1] + xf[5]]
        backups.append({'objectId': node['id'], 'sourceIndex': record['index'], 'originalTextBox': copy.deepcopy(kind),
                        'originalContents': body, 'topLeft': corner, 'lineCount': len(children), 'lines': line_plans})
        node['kind'] = {'type': 'group', 'children': children}
        node['name'] = 'Testo FreeHand ' + str(record['index'])
        converted += 1
        line_count += len(children)
    write_native(path, document, tail)
    report = {'convertedTextBoxes': converted, 'editableLines': line_count, 'skippedTextBoxes': skipped,
              'editingMode': 'individual lines grouped by original text box', 'boxes': backups}
    return report
