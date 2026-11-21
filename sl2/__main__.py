"""python -m sl2"""
import multiprocessing
import sys

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from sl2.cli import main
    sys.exit(main())
