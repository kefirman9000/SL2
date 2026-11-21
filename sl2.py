"""Start SL2.

    python sl2.py                      open the app in your browser
    python sl2.py --no-browser         just start the server
    python sl2.py make "dark deep dubstep, long"   write a song from a description (no UI)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    args = sys.argv[1:]
    if args and args[0] == 'make':
        from sl2 import prompt, store
        s, said = prompt.parse(' '.join(args[1:]))
        print('\n'.join('  ' + x for x in said))

        def prog(p, msg):
            print(f'  {int(p * 100):3d}%  {msg}')
        meta = store.generate(s, progress=prog)
        print(f"\n{meta['title']} - {meta['genre_name']}, {meta['key']}, {meta['bpm']:.0f} BPM")
        print('  ' + '\n  '.join(meta['insights']))
        print('saved to', os.path.join(store.HOME, meta['id']))
        return
    from sl2.server import run
    run(open_browser='--no-browser' not in args)


if __name__ == '__main__':
    main()
