"""2.1 sound checks: the new synths, drums, part effects, master options and the two new genres."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sl2 import fx, synth  # noqa: E402
from sl2 import genres as G  # noqa: E402
from sl2.compose import compose  # noqa: E402

NEW_SYNTHS = ['rumble', 'dub_stab', 'techno_seq', 'dark_pad', 'atmosphere', 'house_organ', 'fuzz_bass', 'fm_epiano', 'wobble_heavy',
              'growl', 'fm_growl', 'talk_growl', 'riddim', 'screech', 'dark_wobble', 'sub_wobble', 'vowel_wobble', 'chop_wobble',
              'neuro', 'reese_deep', 'dnb_wobble', 'metal_bass', 'trance_lead', 'trance_pluck', 'vox_chop']


@pytest.mark.parametrize('inst', NEW_SYNTHS + ['kick_hard', 'kick_rumble', 'snare_heavy', 'clap_reverb'])
def test_new_sounds_render(inst):
    p = {'spb': 0.44, 'rate': 4.5} if inst in synth.TEMPO_SYNCED else {}
    midi = 33 if inst in synth.ROLE_CHOICES['bass'] else 64
    a = synth.play(inst, midi, 0.6, 0.9, p)
    synth._cached.cache_clear()
    b = synth.play(inst, midi, 0.6, 0.9, p)
    assert a.ndim == 2 and a.shape[0] == 2 and a.shape[1] > 1000
    assert np.isfinite(a).all() and 0.01 < np.abs(a).max() <= 1.0
    assert np.allclose(a, b), 'the same note must render the same way every time (any worker process)'
    assert synth.LABELS.get(inst)


@pytest.mark.parametrize('name', list(fx.EFFECTS))
def test_effects(name):
    rng = np.random.default_rng(3)
    x = (rng.standard_normal((2, 44100 * 2)) * 0.2).astype(np.float32)
    for amount in ('light', 'medium', 'heavy'):
        y = fx.apply_chain(x, [fx.preset(name, amount)], 0.47, [[0.0, 1.0], [1.0, 2.0]])
        assert y.shape == x.shape and y.dtype == np.float32 and np.isfinite(y).all()
        assert np.abs(y).max() < 20
    silent = fx.apply_chain(np.zeros((2, 44100), np.float32), [fx.preset(name)], 0.47)
    assert np.abs(silent).max() < 1e-3, 'effects must not make noise out of silence'


def test_effect_chains_are_validated():
    c = fx.clean_chain([['drive', {'amt': '0.5', 'kind': 'evil', 'junk': 1}], ['nope', {}], ['gate', {'pattern': 'x.<b>'}],
                        ['echo', {'mix': float('nan')}], 'garbage'])
    assert c == [['drive', {'amt': 0.5}], ['gate', {}], ['echo', {}]]
    assert len(fx.clean_chain([['eq', {}]] * 20)) == 8


def test_gate_and_pump_follow_the_beat():
    x = np.ones((2, 44100), np.float32) * 0.5
    y = fx.apply_chain(x, [['gate', {'pattern': 'x.x.x.x.x.x.x.x.', 'depth': 1.0}]], 0.5)
    step = int(0.125 * 44100)
    assert y[0, step // 2] > 0.4 and y[0, step + step // 2] < 0.1
    z = fx.apply_chain(x, [['pump', {'beats': 1.0, 'depth': 0.8}]], 0.5)
    assert z[0, 200] < 0.25 and z[0, 20000] > 0.45


def test_master_options():
    from sl2 import render as R
    rng = np.random.default_rng(1)
    t = np.arange(44100 * 6) / 44100
    mix = np.vstack([np.sin(2 * np.pi * 110 * t), np.sin(2 * np.pi * 110 * t + 0.4)]) * 0.3 + rng.standard_normal((2, len(t))) * 0.02
    g = G.load('techno')
    _, club = R.master(mix, g, 0.0, {'loudness': 'club'})
    _, stream = R.master(mix, g, 0.0, {'loudness': 'stream', 'tape': 'on', 'glue': 'heavy', 'tone': 'darker', 'width': 'wide'})
    assert club['lufs'] > stream['lufs'] + 4
    assert abs(stream['lufs'] + 14) < 1.5
    _, bad = R.master(mix, g, 0.0, {'loudness': 'insane', 'x': 1})
    assert 'options' not in bad


def test_genres_use_the_new_sounds_and_effects():
    used = {t['inst'] for gid in G.ids() for t in G.load(gid)['tracks']}
    assert len(set(NEW_SYNTHS) & used) >= 15
    with_fx = [gid for gid in G.ids() if any(t.get('fx') for t in G.load(gid)['tracks'])]
    assert len(with_fx) >= 12
    for gid in G.ids():
        for t in G.load(gid)['tracks']:
            if t.get('fx'):
                assert fx.clean_chain(t['fx']) == t['fx'], (gid, t['id'])


def test_dubstep():
    song = compose(dict(genre='dubstep', seed=2))
    assert song.notes_of('growl') and song.notes_of('sub')
    growl = song.track('growl')
    assert growl.instrument == 'growl' and growl.params.get('fx')
    rates = [n.p.get('rate') for n in song.notes_of('growl')]
    assert all(rates), 'the growl wobbles in time: every note carries its LFO rate'


def test_uk_techno_builds_to_the_end():
    """Modelled on Scuba - NE1BUTU: the final stretch adds parts section by section and ends in a key lift."""
    for seed in (1, 2, 3, 4):
        song = compose(dict(genre='uk_techno', seed=seed))
        drops = [i for i, s in enumerate(song.sections) if s.tags[0] == 'drop']
        tail = drops[-3:]
        counts = [len({t.id for t in song.tracks for p in t.placements if p.section == i}) for i in tail]
        assert counts == sorted(counts) and counts[-1] > counts[0], (seed, counts)
        assert song.notes_of('kick') and all(abs(n.beat % 4 - 2.0) > 0.01 for n in song.notes_of('kick')), 'no kick on beat 3'
        assert song.settings['report'].get('key_lift')


def test_part_effects_survive_a_re_roll(tmp_path, monkeypatch):
    from sl2 import store
    monkeypatch.setattr(store, 'HOME', str(tmp_path))
    monkeypatch.setattr(store, 'STEMS', str(tmp_path / '.stems'))
    m = store.generate(dict(genre='house', seed=1, length='loop'))
    m2 = store.set_fx(m['id'], 'chords', [['gate', {}], ['bogus', {}]])
    song = store.load_song(m2['id'])
    assert song.track('chords').params['fx'] == [['gate', {}]] and song.settings['fx'] == 'normal'
    m3 = store.reroll(m2['id'], 'bass')
    assert store.load_song(m3['id']).track('chords').params['fx'] == [['gate', {}]]
