"""Fetch a private, SHA256-checked MSYS2 UCRT64 toolchain; no system install."""
from pathlib import Path
import hashlib
import json
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
MIRROR = 'https://repo.msys2.org/mingw/ucrt64/'
sys.path.insert(0, str(RUNTIME / 'python'))


def extract(path, destination):
    import zstandard
    with path.open('rb') as source:
        with zstandard.ZstdDecompressor().stream_reader(source) as reader:
            with tarfile.open(fileobj=reader, mode='r|') as archive:
                archive.extractall(destination, filter='data')


def download(url, path):
    print('Download:', url.rsplit('/', 1)[-1], flush=True)
    with urllib.request.urlopen(url, timeout=120) as response:
        path.write_bytes(response.read())


def main():
    cache = RUNTIME / 'packages'
    cache.mkdir(parents=True, exist_ok=True)
    db = cache / 'ucrt64.db'
    download(MIRROR + 'ucrt64.db', db)
    records = {}
    providers = {}
    dbdir = cache / 'database'
    dbdir.mkdir(exist_ok=True)
    extract(db, dbdir)
    for desc in dbdir.glob('*/desc'):
        text = desc.read_text(encoding='utf-8')
        fields = {}
        for block in text.strip().split('\n\n'):
            lines = block.splitlines()
            fields[lines[0].strip('%')] = lines[1:]
        name = fields['NAME'][0]
        records[name] = fields
        for provided in fields.get('PROVIDES', []):
            providers[provided.split('=')[0]] = name
    selected = {}

    def include(name):
        import re
        name = re.split(r'[<>=]', name)[0]
        if name not in records:
            name = providers.get(name, name)
        if name in selected:
            return
        entry = records[name]
        selected[name] = entry
        for dep in entry.get('DEPENDS', []):
            include(dep)

    for name in ['mingw-w64-ucrt-x86_64-gcc', 'mingw-w64-ucrt-x86_64-libfreehand']:
        include(name)
    manifest = []
    for name, entry in sorted(selected.items()):
        filename = entry['FILENAME'][0]
        path = cache / filename
        expected = entry['SHA256SUM'][0]
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            download(MIRROR + filename, path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('SHA256 mismatch: ' + filename)
        extract(path, RUNTIME)
        manifest.append({'name': name, 'version': entry['VERSION'][0], 'url': MIRROR + filename, 'sha256': expected})
        print('Ready:', name, flush=True)
    (RUNTIME / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
