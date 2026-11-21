"""Genre packs: load a genre, resolve what it inherits, and check it against the schema."""
import json
import os

PACKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'packs')


class PackError(ValueError):
    pass


def index(packs_dir=PACKS_DIR):
    """genre id -> path of its pack file."""
    out = {}
    for root, _dirs, files in os.walk(packs_dir):
        for f in files:
            if f.endswith('.json') and not f.startswith('_'):
                gid = f[:-5]
                if gid in out:
                    raise PackError(f'genre {gid!r} is defined twice: {out[gid]} and {os.path.join(root, f)}')
                out[gid] = os.path.join(root, f)
    return out


def _read(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def resolve(path, _seen=None):
    """A pack with everything it extends merged in (the pack's own values win). Whole values are replaced, not merged:
    a genre that lists its own tracks gets exactly those tracks."""
    _seen = _seen or set()
    path = os.path.abspath(path)
    if path in _seen:
        raise PackError(f'circular "extends" at {path}')
    _seen.add(path)
    data = _read(path)
    parent = data.pop('extends', None)
    if parent:
        ppath = os.path.join(os.path.dirname(path), parent + '.json')
        if not os.path.exists(ppath):
            raise PackError(f'{path} extends {parent!r}, which does not exist')
        base = resolve(ppath, _seen)
        base.update(data)
        data = base
    return data


def load(genre_id, packs_dir=PACKS_DIR):
    idx = index(packs_dir)
    if genre_id not in idx:
        raise PackError(f'unknown genre {genre_id!r}')
    data = resolve(idx[genre_id])
    data.pop('id', None)
    return data


REQUIRED = ('name', 'bpm', 'scales', 'tracks')


def validate(data, genre_id='?'):
    """The few rules every genre must meet. Grows into the full schema (docs/GENRE_PACK_SCHEMA.md)."""
    problems = [f'missing {k!r}' for k in REQUIRED if k not in data]
    bpm = data.get('bpm')
    if bpm is not None and not (isinstance(bpm, list) and len(bpm) == 2 and 30 <= bpm[0] <= bpm[1] <= 300):
        problems.append(f'bpm should be [low, high] between 30 and 300, got {bpm!r}')
    for t in data.get('tracks') or []:
        for k in ('name', 'layer', 'inst'):
            if k not in t:
                problems.append(f'track {t.get("name", "?")!r} has no {k!r}')
    if problems:
        raise PackError(f'{genre_id}: ' + '; '.join(problems))
    return data
