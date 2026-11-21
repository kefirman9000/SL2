"""Entry point of the packaged Windows app (SL2.exe)."""
import multiprocessing
import sys

if __name__ == '__main__':
    multiprocessing.freeze_support()          # render workers re-launch SL2.exe; this hands them straight to the worker
    from sl2.cli import main
    sys.exit(main())
