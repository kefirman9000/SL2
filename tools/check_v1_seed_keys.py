"""Show how Studio Lab 1 picks keys: the same seed gives the same key in different genres.

    python tools/check_v1_seed_keys.py /path/to/studio-lab [--seeds 8]

Studio Lab 1 seeds its harmony random generator with the seed only (compose.py: opts.seed * 1009 + 1), not the
genre, so seed N lands on (nearly) the same key everywhere. Studio Lab 2 seeds every random choice with
(seed, genre, part) and keeps this check as a test.
"""
import argparse
import collections
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('v1_path')
    ap.add_argument('--seeds', type=int, default=8)
    ap.add_argument('--genres', default='house,techno,trance,dubstep,liquid_dnb')
    a = ap.parse_args()
    sys.path.insert(0, os.path.abspath(a.v1_path))
    from sgcore.compose import Options, compose
    names = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
    roots = collections.Counter()
    genres = a.genres.split(',')
    for seed in range(1, a.seeds + 1):
        keys = [compose(Options(style=g, seed=seed))['key'] for g in genres]
        roots.update(k.root for k in keys)
        print(f'seed {seed}: ' + ', '.join(f'{g}={k.name()}' for g, k in zip(genres, keys)))
    total = sum(roots.values())
    print('\nkey roots over', total, 'songs (a fair spread is about', round(100 / 12), '% each):')
    for r in range(12):
        print(f'  {names[r]:3} {100 * roots[r] / total:5.1f}%')


if __name__ == '__main__':
    main()
