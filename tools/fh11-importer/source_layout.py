"""Read the line layout saved by FreeHand, before any modern text reflow."""
import json
import math
import struct


def read_layout(diagnostics):
    records, references, tables = [], {}, {}
    for line in diagnostics.decode('utf-8', 'replace').split('\n'):
        if line.startswith('FHTEXT '):
            records.append(json.loads(line[7:]))
        elif line.startswith('FHLINEREF '):
            _, frame, table = line.split()
            references[int(frame)] = int(table)
        elif line.startswith('FHLINEROW '):
            _, table, index, hexdata, reference = line.split()
            data = bytes.fromhex(hexdata)
            if len(data) != 48:
                raise ValueError('Invalid FreeHand line record')
            row = {name: struct.unpack_from('>i', data, offset)[0] / 65536
                   for name, offset in [('x', 0), ('y', 4), ('width', 8), ('size', 32), ('leading', 44)]}
            row.update(start=struct.unpack_from('>H', data, 12)[0],
                       length=struct.unpack_from('>H', data, 14)[0],
                       index=int(index), reference=int(reference))
            if not all(math.isfinite(row[key]) for key in ['x', 'y', 'width', 'size', 'leading']):
                raise ValueError('Non-finite FreeHand line record')
            tables.setdefault(int(table), []).append(row)
    for record in records:
        table = references.get(int(record['props'].get('fhi:vmp', 0)))
        record['lines'] = tables.get(table, [])
    return records


def uniform_leading(record):
    rows = record.get('lines', [])
    gaps = [a['y'] - b['y'] for a, b in zip(rows, rows[1:])]
    if gaps and all(0 < value < 10000 for value in gaps) and max(gaps) - min(gaps) < .01:
        return sum(gaps) / len(gaps)
    return None
