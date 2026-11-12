# FreeHand MX importer for VectorCraft

This experimental desktop integration opens `.fh11` from File > Open when
`VECTORCRAFT_FH11_CONVERTER` points to the companion executable. VectorCraft
passes the source path and a temporary output directory to the converter, then
opens its `documento.vectorcraft` as a new document. The source is read only.

The converter keeps one editable area text object per FreeHand frame and uses
the saved line table to preserve line breaks and baseline spacing where
available. On Windows, it asks for Arial's Narrow face for Arial Narrow text.
It requests the Light face of BookmanITC Lt BT for the regular Bookman text in
FreeHand. The matching font files need to be available to VectorCraft.

## Build and run on Windows x64

Run these commands from this directory with Python 3.12 or later and a
working VectorCraft desktop/CLI build.

```powershell
python -m pip install --target .runtime/python zstandard
python -m pip install --target .runtime/packaging pyinstaller
python tools/bootstrap_runtime.py
python tools/build_pages.py --test
python -m unittest discover -s tests -v
python tools/build_portable.py
```

Set these variables in the shell that launches the desktop build.

```powershell
$env:VECTORCRAFT_FH11_CONVERTER = (Resolve-Path 'output/FreeHandImporter-Portable/FreeHandImporter.exe').Path
$env:FREEHAND_VECTORCRAFT_CLI = (Resolve-Path 'C:/path/to/vectorcraft-cli.exe').Path
```

The parser build downloads a checksum-pinned libfreehand 0.1.3 archive and
applies the changes in `tools/build_pages.py`. Modified libfreehand sources
retain their MPL-2.0 notices in the local build tree. The VectorCraft branch
uses the resulting standalone tool as a separate process.
