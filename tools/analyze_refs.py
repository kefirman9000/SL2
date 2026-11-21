"""Measure reference tracks and save the numbers (never the audio).

    python tools/analyze_refs.py [--bpm HINT] OUT.json FILE [FILE ...]
"""
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sl2.analyze import analyze  # noqa: E402


HINT = None


def one(p):
    try:
        return analyze(p, bpm_hint=HINT)
    except Exception as e:  # keep going with the others
        return dict(file=os.path.basename(p), error=str(e))


def _init(h):
    global HINT
    HINT = h


if __name__ == '__main__':
    args = sys.argv[1:]
    if args[0] == '--bpm':
        HINT = float(args[1])
        args = args[2:]
    out, files = args[0], args[1:]
    with ProcessPoolExecutor(max_workers=os.cpu_count(), initializer=_init, initargs=(HINT,)) as ex:
        res = list(ex.map(one, files))
    json.dump(res, open(out, 'w'), indent=1)
    for r in res:
        print(r['file'][:50], r.get('error') or f"{r['bpm']} BPM  {r['key']}  lufs {r['lufs']}  kick {r['drums']['kick']}  snare {r['drums']['snare']}")
