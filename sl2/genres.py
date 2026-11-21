"""Genre packs (sl2/genres/*.json).

A pack may say "extends": "<family>" (files starting with _). Settings that are dicts (harmony, bass, lead ...) are
merged one level deep, so a genre only writes what it changes; everything else (drums, tracks, forms) is replaced
whole - each genre keeps its own drums, sounds and song forms rather than borrowing them.
"""
import functools
import json
import os

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'genres')
MERGE = {'harmony', 'bass', 'chords', 'lead', 'arp', 'sidechain', 'drum_flags', 'fingerprint', 'riff'}


class GenreError(ValueError):
    pass


def _read(name):
    p = os.path.join(DIR, name + '.json')
    if not os.path.exists(p):
        raise GenreError(f'no genre pack {name!r}')
    with open(p, encoding='utf-8') as f:
        return json.load(f)


@functools.lru_cache(maxsize=None)
def _resolved(name):
    d = _read(name)
    parent = d.pop('extends', None)
    if not parent:
        return d
    base = json.loads(json.dumps(_resolved(parent)))
    for k, v in d.items():
        if k in MERGE and isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = dict(base[k], **v)
        else:
            base[k] = v
    return base


def ids():
    return sorted(f[:-5] for f in os.listdir(DIR) if f.endswith('.json') and not f.startswith('_'))


def load(gid):
    g = json.loads(json.dumps(_resolved(gid)))
    g['id'] = gid
    validate(g)
    return g


def all_genres():
    return {g: load(g) for g in ids()}


def validate(g):
    probs = []
    for k in ('name', 'bpm', 'scales', 'forms', 'drums', 'tracks', 'harmony'):
        if k not in g:
            probs.append(f'missing {k!r}')
    if 'bpm' in g and not (len(g['bpm']) == 2 and 40 <= g['bpm'][0] <= g['bpm'][1] <= 220):
        probs.append(f"bad bpm {g['bpm']}")
    from .synth import known
    seen = set()
    for t in g.get('tracks', []):
        if t['id'] in seen:
            probs.append(f"track id {t['id']!r} twice")
        seen.add(t['id'])
        if not known(t['inst']):
            probs.append(f"track {t['id']!r}: unknown instrument {t['inst']!r}")
    for lvl in ('low', 'mid', 'high'):
        for v, pat in (g.get('drums', {}).get(lvl) or {}).items():
            if len(pat) % 16:
                probs.append(f'drums.{lvl}.{v}: pattern length {len(pat)} is not a multiple of 16')
    if probs:
        raise GenreError(f"{g.get('id', '?')}: " + '; '.join(probs))
    return g


def summary():
    out = []
    for gid, g in all_genres().items():
        out.append(dict(id=gid, name=g['name'], desc=g.get('desc', ''), group=g.get('group', ''), bpm=g['bpm'],
                        keywords=g.get('keywords', []), refs=g.get('refs', '')))
    return sorted(out, key=lambda x: (x['group'], x['name']))
