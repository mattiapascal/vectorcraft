"""Build a relocatable Windows x64 folder with Python/Tk and our patched parser."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
DLLS = ['libgcc_s_seh-1.dll', 'liblcms2-2.dll', 'librevenge-0.0.dll',
        'librevenge-stream-0.0.dll', 'libstdc++-6.dll', 'libwinpthread-1.dll',
        'libz-1.dll', 'zlib1.dll']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'output/FreeHandImporter-Portable')
    target = parser.parse_args().out.resolve()
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT / '.runtime/packaging')
    env['PYINSTALLER_CONFIG_DIR'] = str(ROOT / 'build/pyinstaller-cache')
    if target.exists():
        raise RuntimeError('Destinazione esistente: conservare o rinominare la precedente compilazione.')
    build = (ROOT / 'build').resolve()
    dist = build / f'portable-dist-{uuid.uuid4().hex}'
    dist.mkdir()
    try:
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--onedir', '--windowed',
                        '--name', 'FreeHandImporter', '--noupx', '--distpath', str(dist),
                        '--workpath', str(build / 'portable-work'),
                        '--specpath', str(build), str(ROOT / 'launch.py')],
                       env=env, cwd=ROOT, check=True)
        shutil.copytree(dist / 'FreeHandImporter', target)
    finally:
        if dist.resolve().parent == build and not dist.is_symlink():
            shutil.rmtree(dist)
    (target / 'build').mkdir()
    shutil.copy2(ROOT / 'build/fh_extract_pages.exe', target / 'build')
    dll_folder = target / '.runtime/ucrt64/bin'
    dll_folder.mkdir(parents=True)
    for name in DLLS:
        shutil.copy2(ROOT / '.runtime/ucrt64/bin' / name, dll_folder)
    licenses = target / 'licenses'
    licenses.mkdir()
    for name in ('librevenge', 'lcms2', 'gcc-libs', 'zlib', 'libwinpthread', 'libfreehand'):
        source = ROOT / '.runtime/ucrt64/share/licenses' / name
        if source.is_dir():
            shutil.copytree(source, licenses / name)
    shutil.copy2(ROOT / 'LEGGIMI-PORTABLE.txt', target)
    shutil.copy2(ROOT / 'Avvia Importatore.cmd', target)
    shutil.make_archive(str(target), 'zip', target.parent, target.name)
    print(target)


if __name__ == '__main__':
    main()
