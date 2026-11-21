"""Start SL2.

    python sl2.py                      open the app in your browser
    python sl2.py --no-browser         just start the server
    python sl2.py make "dark deep dubstep, long"   write a song from a description (no UI)
"""
import multiprocessing
import os
import sys

if __name__ == '__main__':
    multiprocessing.freeze_support()          # the Windows app starts its render workers from this same file
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if sys.version_info < (3, 9):
        sys.exit('SL2 needs Python 3.9 or newer (https://www.python.org/downloads/)')
    from sl2.cli import main
    sys.exit(main())
