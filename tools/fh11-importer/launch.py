"""Entry point for the Python launcher and portable Windows/macOS builds."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    parser = argparse.ArgumentParser(description='FreeHand Importer personale')
    parser.add_argument('--check', type=Path, help='Scrivi una diagnosi JSON senza aprire finestre')
    parser.add_argument('--convert', type=Path, help='Converti un documento senza aprire la finestra')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--ai', action='store_true')
    args = parser.parse_args()
    from freehand_bridge import ROOT, VECTORCRAFT, convert, find_extractor, run, runtime_env
    if args.check:
        import tkinter
        engine = find_extractor()
        version = run([str(engine), '--version'], env=runtime_env()).stdout.decode().strip()
        args.check.write_text(json.dumps({
            'portable': bool(getattr(sys, 'frozen', False)),
            'python': sys.version.split()[0], 'tk': tkinter.TkVersion,
            'applicationRoot': str(ROOT), 'parser': version,
            'vectorcraftCLI': str(VECTORCRAFT), 'vectorcraftFound': VECTORCRAFT.is_file(),
        }, indent=2), encoding='utf-8')
        return
    if args.convert:
        if not args.out:
            parser.error('--convert richiede --out')
        convert(args.convert, args.out, ai=args.ai)
        return
    from gui import main as show_window
    show_window()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        details = traceback.format_exc()
        from platform_support import user_settings_root
        folder = user_settings_root()
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / 'ultimo-errore.txt'
        log.write_text(details, encoding='utf-8')
        if sys.stderr:
            sys.stderr.write(details)
        if not any(arg in sys.argv for arg in ('--check', '--convert')):
            message = 'Avvio non riuscito. Dettagli salvati in:\n' + str(log)
            if sys.platform == 'win32':
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, message, 'FreeHand Importer', 16)
            else:
                try:
                    from tkinter import messagebox
                    messagebox.showerror('FreeHand Importer', message)
                except Exception:
                    pass
        raise SystemExit(1)
