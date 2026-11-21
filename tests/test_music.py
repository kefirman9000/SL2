"""Musical-quality checks (2.1): the things that make a generated song sound written rather than looped.

These measure the composed song itself - notes against the chords that actually sound, how much the bars change,
whether later drops differ - so a change that quietly brings back a loop or a clash fails here.
"""
import collections
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sl2 import edit as E  # noqa: E402
from sl2.compose import compose  # noqa: E402
from sl2.song import Song  # noqa: E402

MELODIC = ['trance', 'deep_house', 'liquid_dnb', 'synthwave', 'trap', 'garage', 'sunlit', 'lofi', 'phonk', 'dnb']


def _sounding_pcs(song):
    """16th step -> pitch classes the chords / pad play there."""
    at = collections.defaultdict(set)
    for t in song.tracks:
        if t.role in ('chords', 'pad'):
            for n in song.notes_of(t.id):
                for q in range(int(round(n.beat * 4)), int(round((n.beat + n.length) * 4))):
                    at[q].add(n.pitch % 12)
    return at


def _sec_of(song, beat):
    for i, s in enumerate(song.sections):
        if s.start_bar * 4 <= beat < (s.start_bar + s.bars) * 4:
            return i


@pytest.mark.parametrize('gid', MELODIC)
def test_lead_fits_the_chords_in_every_section(gid):
    """Strong-beat lead notes are chord tones of the chord that sounds - breakdowns included (2.0 wrote the
    breakdown line over the main progression while the chords played another one)."""
    for seed in (1, 2, 3, 4):
        song = compose(dict(genre=gid, seed=seed))
        ch = _sounding_pcs(song)
        notes = [n for t in song.tracks if t.role == 'lead' for n in song.notes_of(t.id)]
        per_kind = collections.defaultdict(lambda: [0, 0])
        for i, n in enumerate(notes):
            q = int(round(n.beat * 4))
            if q % 8 or not ch.get(q):
                continue
            k = song.sections[_sec_of(song, n.beat)].tags[0]
            per_kind[k][0] += 1
            ok = n.pitch % 12 in ch[q]
            if not ok and i + 1 < len(notes):          # a leaning note that resolves by step is fine
                nx = notes[i + 1]
                ok = abs(nx.pitch - n.pitch) <= 2 and nx.pitch % 12 in ch.get(int(round(nx.beat * 4)), ())
            per_kind[k][1] += ok
        for k, (tot, ok) in per_kind.items():
            assert ok / tot >= 0.85, f'{gid} seed {seed}: only {ok}/{tot} strong-beat lead notes fit the chords in {k}'


@pytest.mark.parametrize('gid', MELODIC)
def test_lead_never_drops_out_at_the_end_of_a_section(gid):
    """A section whose length isn't a whole number of phrases still gets its lead to the end (2.0 left the last
    bars silent)."""
    for seed in (1, 2, 3):
        for length in ('short', 'long'):
            song = compose(dict(genre=gid, seed=seed, length=length, variation='low'))
            for t in song.tracks:
                if t.role != 'lead':
                    continue
                on = set()
                for n in song.notes_of(t.id):
                    for b in range(int(n.beat // 4), int(math.ceil((n.beat + n.length) / 4))):
                        on.add(b)
                for s in song.sections:
                    bars = list(range(s.start_bar, s.start_bar + s.bars))
                    if not any(b in on for b in bars):
                        continue
                    tail = 0
                    for b in reversed(bars):
                        if b in on:
                            break
                        tail += 1
                    assert tail <= 2, f'{gid} {length} seed {seed}: {t.id} silent for the last {tail} bars of {s.name}'


def test_chord_voicings_have_no_semitone_clusters():
    for gid in ('deep_house', 'liquid_dnb', 'sunlit', 'garage', 'lofi', 'ambient'):
        for seed in range(1, 7):
            song = compose(dict(genre=gid, seed=seed))
            for t in song.tracks:
                if t.role not in ('chords', 'pad'):
                    continue
                by = collections.defaultdict(list)
                for n in song.notes_of(t.id):
                    by[round(n.beat, 2)].append(n.pitch)
                for b, ps in by.items():
                    ps = sorted(ps)
                    assert not any(y - x == 1 for x, y in zip(ps, ps[1:])), f'{gid} seed {seed} {t.id} at beat {b}: {ps}'


def test_chord_colour_rules():
    """A 9th a semitone above the root (b9) is left out; colour notes that clash a semitone with the triad move up."""
    from sl2.theory import Key, color_pcs, declutter
    k = Key(4, 'minor')                         # E minor: the 9th of ii (F#) is fine, of the v (B) is C# - fine; of III (G)...
    for deg in range(7):
        pcs, core = color_pcs(k, deg, 4, True)
        assert all((p - core[0]) % 12 != 1 for p in pcs[3:])
    assert declutter([64, 65, 68, 72], {65, 68, 72}, 76) == [65, 68, 72, 76]


def _distinct_bars(song, role):
    t = next((t for t in song.tracks if t.role == role), None)
    if t is None:
        return None
    bars = collections.defaultdict(list)
    for n in song.notes_of(t.id):
        bars[int(n.beat // 4)].append((round(n.beat % 4, 2), n.pitch))
    return len({tuple(sorted(v)) for v in bars.values()}) / max(1, len(bars))


def test_songs_are_not_bar_for_bar_loops():
    """Hats and snares/claps change at the ends of phrases (2.0: 3-5% of hat bars differed from each other)."""
    for gid, role in (('trance', 'hat'), ('house', 'hat'), ('dnb', 'snare'), ('techno', 'hat'), ('deep_house', 'clap')):
        vals = [_distinct_bars(compose(dict(genre=gid, seed=s)), role) for s in range(1, 6)]
        assert np.mean(vals) >= 0.06, (gid, role, vals)


def test_later_drops_change():
    for gid in ('trance', 'liquid_dnb', 'synthwave'):
        changed = 0
        for seed in range(1, 7):
            song = compose(dict(genre=gid, seed=seed))
            if song.settings['report'].get('later_drops'):
                changed += 1
        assert changed >= 5, gid
    assert not compose(dict(genre='trance', seed=1, variation='low')).settings['report'].get('later_drops')


def test_trance_breakdown_carries_the_theme():
    song = compose(dict(genre='trance', seed=2))
    theme = song.notes_of('theme')
    breaks = [s for s in song.sections if s.tags[0] == 'break']
    assert theme and breaks
    assert all(any(s.start_bar * 4 <= n.beat < (s.start_bar + s.bars) * 4 for n in theme) for s in breaks)


def test_call_and_response():
    for gid in ('deep_house', 'trance', 'synthwave', 'liquid_dnb', 'sunlit', 'garage'):
        plays = sum(any(t.id == 'answer' for t in compose(dict(genre=gid, seed=s)).tracks) for s in range(1, 7))
        assert plays >= 3, f'{gid}: the answer part played in only {plays} of 6 songs'   # it stays out when the lead leaves no room
    song = compose(dict(genre='deep_house', seed=4))
    ans = song.notes_of('answer')
    assert ans, 'the answer part should play in the drops'
    lead_on = {round(n.beat * 4) for n in song.notes_of('lead')}
    overlap = sum(1 for n in ans if round(n.beat * 4) in lead_on) / len(ans)
    assert overlap < 0.25, 'the answer should fill the gaps the lead leaves, not double it'


def test_new_lead_devices():
    house = compose(dict(genre='house', seed=1))
    techno = compose(dict(genre='techno', seed=1))
    assert house.notes_of('chops') and house.settings['report']['melody']['device'] == 'chops'
    assert techno.notes_of('seq') and techno.settings['report']['melody']['device'] == 'ostinato'


def test_melody_critic_tells_candidates_apart():
    for gid in ('trance', 'liquid_dnb', 'synthwave'):
        for seed in (1, 2, 3):
            m = compose(dict(genre=gid, seed=seed)).settings['report']['melody']
            assert m['score'] - m['median'] >= 1.0, m      # the winner is clearly better than a typical candidate


def test_feel_settings():
    sparse = compose(dict(genre='trance', seed=1, hats='sparse'))
    assert all(round(n.beat * 4) % 2 == 0 for n in sparse.notes_of('hat') if abs(n.beat * 4 - round(n.beat * 4)) < 0.05)
    none = sum(len(compose(dict(genre='dnb', seed=s, fills='none')).notes_of('snare')) for s in (1, 2))
    more = sum(len(compose(dict(genre='dnb', seed=s, fills='more')).notes_of('snare')) for s in (1, 2))
    assert more > none
    assert not any(s.tags[0] == 'build' for s in compose(dict(genre='trance', seed=1, builds='off')).sections)
    loop = compose(dict(genre='trance', seed=1, length='loop'))
    assert len(loop.sections) == 1 and loop.sections[0].bars == 16 and loop.sections[0].tags[0] == 'drop'
    off = compose(dict(genre='trance', seed=1, fx='off'))
    assert not any(t.id == 'fx' for t in off.tracks)
    bad = compose(dict(genre='trance', seed=1, hats='nonsense', length='weird'))      # unknown values fall back
    assert bad.settings['hats'] == 'normal' and bad.settings['length'] == 'normal'


def test_intro_parts_enter_on_the_grid():
    song = compose(dict(genre='trance', seed=5))
    intro = song.sections[0]
    firsts = []
    for t in song.tracks:
        ns = [n.beat for n in song.notes_of(t.id) if n.beat < intro.bars * 4 and t.role != 'fx']
        if ns:
            firsts.append(min(ns))
    assert any(f >= 16 for f in firsts), 'some parts should come in later than the first bar of the intro'


def test_harmony_colour():
    """Minor keys can use a major V (raised leading tone); every part then plays the raised note, not the plain one."""
    found = False
    for seed in range(1, 30):
        song = compose(dict(genre='trance', seed=seed))
        prog = song.settings['report']['progression']
        if 'V' in prog.split(' – ') and 'minor' in song.key:
            found = True
            from sl2.theory import Key, parse_key
            k = Key(*parse_key(song.key))
            natural7 = k.pc(6)
            main = song.settings['harmony']['main']
            for t in song.tracks:
                if t.role not in ('chords', 'pad', 'arp'):
                    continue
                for n in song.notes_of(t.id):
                    sec = song.sections[_sec_of(song, n.beat)]
                    deg = main[((int(n.beat // 4) - sec.start_bar) // 2) % len(main)]
                    if deg == 4 and abs(n.beat - round(n.beat)) < 1e-6 and n.beat % 8 == 0:
                        assert n.pitch % 12 != natural7, (seed, t.id, n)
            break
    assert found


# ------------------------------------------------------------------ section editing
def _all_notes(song):
    return sorted((t.id, round(n.beat, 3), n.pitch) for t in song.tracks for n in song.notes_of(t.id))


def test_section_edits_keep_the_notes():
    song = compose(dict(genre='synthwave', seed=2, length='short'))
    bars0 = song.total_bars()
    n1 = song.sections[1].bars
    a = Song.from_json(song.to_json())
    E.apply(a, 1, 'duplicate')
    assert a.total_bars() == bars0 + n1 and a.sections[1].name == a.sections[2].name
    E.apply(a, 2, 'remove')
    assert _all_notes(a) == _all_notes(song), 'duplicate then remove should give the original back'
    E.apply(a, 1, 'longer', bars=4)
    assert a.sections[1].bars == n1 + 4 and a.total_bars() == bars0 + 4
    E.apply(a, 1, 'shorter', bars=4)
    assert a.total_bars() == bars0
    E.apply(a, 1, 'right')
    assert a.sections[2].name == song.sections[1].name
    E.apply(a, 0, 'mute', track='kick')
    assert not [n for n in a.notes_of('kick') if n.beat < a.sections[0].bars * 4]
    assert a.settings['form_override'][2][0] == song.sections[1].name and a.settings['section_mutes'] == {'0': ['kick']}
    b = Song.from_json(a.to_json())
    assert _all_notes(b) == _all_notes(a)
    with pytest.raises(ValueError):
        E.apply(a, 99, 'remove')


def test_a_re_roll_keeps_an_edited_layout():
    song = compose(dict(genre='trance', seed=2, length='short'))
    E.apply(song, 1, 'duplicate')
    s = dict(song.settings, part_seeds={'track-bass': 1})
    again = compose(s)
    assert [(x.name, x.bars) for x in again.sections] == [(x.name, x.bars) for x in song.sections]
    first = song.sections[1].start_bar * 4
    assert [n.beat for n in again.notes_of('kick') if n.beat < first] == [n.beat for n in song.notes_of('kick') if n.beat < first]


# ------------------------------------------------------------------ sound engine bits
def test_filter_sweeps():
    from sl2 import render as R
    sr = R.SR
    rng = np.random.default_rng(0)
    x = rng.standard_normal((2, sr * 2)).astype(np.float32) * 0.1
    y = R.apply_sweeps(x, {'hp': [[0.0, 2.0, 30.0, 2000.0]]})

    def low(z):
        f = np.fft.rfft(z[0]) ** 2
        fr = np.fft.rfftfreq(len(z[0]), 1 / sr)
        return float(np.abs(f[fr < 300]).sum() / np.abs(f).sum())
    assert low(y[:, -sr // 4:]) < 0.2 * low(x[:, -sr // 4:]), 'the end of a high-pass ramp should have little low end'
    assert np.isfinite(y).all()


def test_song_automation_round_trip():
    song = compose(dict(genre='trance', seed=1))
    assert any(t.automation for t in song.tracks)
    back = Song.from_json(song.to_json())
    assert [t.automation for t in back.tracks] == [t.automation for t in song.tracks]


def test_windows_helpers(tmp_path):
    from sl2 import render as R
    assert 1 <= R.default_workers() <= 61
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.write_text('new')
    b.write_text('old')
    R.replace_file(str(a), str(b))
    assert b.read_text() == 'new'
