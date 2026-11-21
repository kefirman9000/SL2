"""Convert Studio Lab 1's genre library (sgcore/styles.py) into Studio Lab 2 genre packs.

    python tools/convert_v1_styles.py /path/to/studio-lab [--out packs]

Studio Lab 1 keeps every genre as one big Python dict. Studio Lab 2 keeps them as JSON packs with inheritance:

    packs/<tab>/<group>/_family.json   settings every genre in the group shares
    packs/<tab>/<group>/<genre>.json   only what this genre changes ({"extends": "_family", ...})

A family setting is one that every genre in the group has with exactly the same value, so nothing changes when
the packs are resolved again: tests/test_packs.py checks that every resolved pack equals the v1 dict it came from.
"""
import argparse
import json
import os
import re
import sys


def _plain(o):
    """v1 values -> JSON values (tuples become lists, sets become sorted lists)."""
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    if isinstance(o, (set, frozenset)):
        return sorted(_plain(v) for v in o)
    return o


def slug(s):
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')


def load_v1(v1_path):
    sys.path.insert(0, os.path.abspath(v1_path))
    from sgcore.styles import STYLES
    from sgcore.genre_groups import GROUPS
    return STYLES, GROUPS


def build_packs(styles, groups):
    """-> {(tab, group): {'_family': {...}, genre_id: {...overrides}}}"""
    plain = {k: _plain(v) for k, v in styles.items()}
    placed, out = set(), {}
    for tab, tab_groups in groups.items():
        for group, ids in tab_groups:
            ids = [i for i in ids if i in plain]
            if not ids:
                continue
            members = [plain[i] for i in ids]
            family = {}
            if len(members) > 1:
                for key, val in members[0].items():
                    if key in ('name', 'desc'):
                        continue
                    if all(key in m and m[key] == val for m in members[1:]):
                        family[key] = val
            files = {'_family': family}
            for i in ids:
                own = {k: v for k, v in plain[i].items() if k not in family}
                files[i] = dict({'id': i, 'extends': '_family'}, **own)
                placed.add(i)
            out[(slug(tab), slug(group))] = files
    rest = [i for i in plain if i not in placed]         # genres v1 has not filed in a group
    if rest:
        out[('more', 'unsorted')] = dict({'_family': {}}, **{i: dict({'id': i, 'extends': '_family'}, **plain[i]) for i in rest})
    return out


def write_packs(packs, out_dir):
    n = 0
    for (tab, group), files in packs.items():
        d = os.path.join(out_dir, tab, group)
        os.makedirs(d, exist_ok=True)
        for name, data in files.items():
            with open(os.path.join(d, name + '.json'), 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
                f.write('\n')
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('v1_path', help='a checkout of kefirman9000/studio-lab')
    ap.add_argument('--out', default='packs')
    a = ap.parse_args()
    styles, groups = load_v1(a.v1_path)
    packs = build_packs(styles, groups)
    n = write_packs(packs, a.out)
    v1_keys = sum(len(v) for v in styles.values())
    v2_keys = sum(len(d) - (2 if k != '_family' else 0) for files in packs.values() for k, d in files.items())
    print(f'{len(styles)} genres -> {len(packs)} families, {n} files in {a.out}/')
    print(f'settings written: {v1_keys} in v1 -> {v2_keys} with families')


if __name__ == '__main__':
    main()
