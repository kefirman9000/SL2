"""SL2 from the command line (also the entry point of the Windows app).

    sl2                       open the app (its own window in the Windows program; your browser otherwise)
    sl2 --window              open the app in its own window (needs pywebview)
    sl2 --browser             open the app in your browser
    sl2 --no-browser          just start the server
    sl2 make "dark deep dubstep, long"   write a song from a description (no UI)
"""
import os
import sys


def _console_utf8():
    """Windows consoles default to a legacy code page that can't print every character SL2 uses (arrows, dashes);
    print UTF-8 instead of crashing, and replace anything the console still can't show."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    _console_utf8()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return 0
    if args and args[0] == '--version':
        from . import __version__
        print('SL2', __version__)
        return 0
    if args and args[0] == 'make':
        from . import prompt, store
        s, said = prompt.parse(' '.join(args[1:]))
        print('\n'.join('  ' + x for x in said))

        def prog(p, msg):
            print(f'  {int(p * 100):3d}%  {msg}', flush=True)
        meta = store.generate(s, progress=prog)
        print(f"\n{meta['title']} - {meta['genre_name']}, {meta['key']}, {meta['bpm']:.0f} BPM")
        print('  ' + '\n  '.join(meta['insights']))
        print('saved to', os.path.join(store.HOME, meta['id']))
        return 0
    if '--selftest' in args:
        from . import desktop
        return desktop.run(selftest=args[args.index('--selftest') + 1])
    if '--window' in args or (default_window() and not {'--browser', '--no-browser'} & set(args)):
        from . import desktop
        return desktop.run()
    from .server import run
    run(open_browser='--no-browser' not in args)
    return 0


def default_window():
    """The installed Windows program (SL2.exe) opens its own window; sl2-cli.exe and `python sl2.py` use the browser."""
    if not getattr(sys, 'frozen', False):
        return False
    return not os.path.basename(sys.executable).lower().startswith('sl2-cli')
