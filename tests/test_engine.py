"""SL2 engine tests: genre packs, composition, uniqueness between genres, prompt parsing, rendering, analysis."""
import collections
import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sl2 import genres as G  # noqa: E402
from sl2 import prompt  # noqa: E402
from sl2.compose import compose  # noqa: E402
from sl2.theory import Key, voice_lead  # noqa: E402

IDS = G.ids()


def test_every_genre_pack_is_valid():
    assert len(IDS) >= 15
    for gid in IDS:
        G.load(gid)


@pytest.mark.parametrize('gid', IDS)
def test_compose_every_genre(gid):
    a = compose(dict(genre=gid, seed=5, length='short'))
    b = compose(dict(genre=gid, seed=5, length='short'))
    assert a.to_json() == b.to_json(), 'same settings must give the same song'
    assert a.tracks and sum(len(c.notes) for c in a.clips.values()) > 50
    lo, hi = G.load(gid)['bpm']
    assert lo <= a.bpm <= hi


def test_keys_spread_over_seeds_and_genres():
    """Studio Lab 1 picked Eb for 30% of songs; every seed now draws its own key per genre."""
    roots = collections.Counter()
    same = 0
    for seed in range(1, 13):
        ks = [compose(dict(genre=g, seed=seed, length='short')).key.split()[0] for g in ('house', 'techno', 'trance', 'liquid_dnb')]
        roots.update(ks)
        same += len(set(ks)) == 1
    assert len(roots) >= 9, roots
    assert max(roots.values()) / sum(roots.values()) < 0.2, roots
    assert same <= 1


def test_reroll_one_part_keeps_the_others():
    a = compose(dict(genre='liquid_dnb', seed=2, length='short'))
    b = compose(dict(genre='liquid_dnb', seed=2, length='short', part_seeds={'melody': 1}))
    assert a.notes_of('kick') == b.notes_of('kick')
    assert a.notes_of('bass') == b.notes_of('bass')
    assert a.notes_of('lead') != b.notes_of('lead')


def test_locked_track_survives_new_harmony():
    a = compose(dict(genre='deep_house', seed=4, length='short'))
    lead = [(n.beat, n.length, n.pitch, n.velocity) for n in a.notes_of('lead')]
    b = compose(dict(genre='deep_house', seed=4, length='short', part_seeds={'harmony': 3}), locked={'lead': lead})
    assert [(n.beat, n.pitch) for n in b.notes_of('lead')] == [(x[0], x[2]) for x in lead]


def _signature(gid):
    g = G.load(gid)
    insts = {t['inst'] for t in g['tracks'] if t['role'] != 'fx'}
    kick = (g['drums'].get('mid') or {}).get('kick', '')
    return insts, kick, tuple(g['bpm']), g.get('bass', {}).get('style')


def test_genres_are_distinct():
    """No two genres may share most of their sounds AND their groove AND their tempo range AND bass style."""
    sigs = {gid: _signature(gid) for gid in IDS}
    for a in IDS:
        for b in IDS:
            if a >= b:
                continue
            ia, ka, ra, ba = sigs[a]
            ib, kb, rb, bb = sigs[b]
            jac = len(ia & ib) / len(ia | ib)
            overlap = min(ra[1], rb[1]) - max(ra[0], rb[0]) >= 0
            assert not (jac > 0.75 and ka == kb and overlap and ba == bb), f'{a} and {b} are too alike'


def test_voice_leading_moves_little():
    k = Key(0, 'minor')
    v1 = voice_lead(k.chord_pcs(0), None, 52, 76)
    v2 = voice_lead(k.chord_pcs(5), v1, 52, 76)
    assert sum(abs(a - b) for a, b in zip(sorted(v1), sorted(v2))) <= 5


def test_prompt():
    s, said = prompt.parse('dark rolling liquid dnb in F minor, long, 174 bpm, called Night Bus')
    assert s['genre'] == 'liquid_dnb' and s['key'] == 'F minor' and s['bpm'] == 174 and s['length'] == 'long'
    assert s['title'] == 'Night Bus'
    s, _ = prompt.parse('spooky surf rock like a monster tv theme')
    assert s['genre'] == 'spooky_surf'
    s, _ = prompt.parse('some sunny deep house')
    assert s['genre'] == 'deep_house'


def test_render_and_analyse_round_trip():
    """Render a short song, then measure it: the analyser must find its tempo."""
    from sl2 import render as R
    from sl2.analyze import analyze
    song = compose(dict(genre='techno', seed=1, length='short', bpm=130))
    with tempfile.TemporaryDirectory() as d:
        paths, infos = R.render_stems(song, d, workers=2)
        mx = R.mix_stems(paths, song)
        m, rep = R.master(mx, G.load('techno'))
        assert np.isfinite(m).all() and np.abs(m).max() <= 0.9 + 1e-3
        assert abs(rep['lufs'] - rep['target_lufs']) < 1.5
        wav = os.path.join(d, 'x.wav')
        R.write_wav(wav, m)
        a = analyze(wav, bpm_hint=128)
        assert abs(a['bpm'] - 130) < 1.5, a['bpm']
