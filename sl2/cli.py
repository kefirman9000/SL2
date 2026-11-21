"""SL2 from the command line (also the entry point of the Windows app).

    sl2                       open the app in your browser
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
    from .server import run
    run(open_browser='--no-browser' not in args)
    return 0
