"""The composer: settings + a genre pack -> a Song document (sections, tracks, notes) and a short report.

Every random choice has its own generator seeded by (seed, genre, part), so:
  - the same seed in two genres gives two unrelated songs (different keys, tempos, progressions);
  - re-rolling one part (settings['part_seeds']) changes only that part.
Locked tracks (locked={track_id: [(beat, len, midi, vel)]}) are kept note for note; if the harmony is re-rolled under
a locked melody, the new chord loop is chosen to fit that melody.
"""
import math

from . import genres as G
from .melody import fit_to_locked, skeleton, verse_variant, write_hook
from .song import Clip, Note, Placement, Section, Song, Track
from .theory import Key, NOTE_NAMES, parse_key, rng, voice_lead

VEL = {'X': 1.0, 'x': 0.78, 'o': 0.55, 'g': 0.32}
DRUM_ROLES = {'kick', 'snare', 'clap', 'hat', 'ohat', 'ride', 'shaker', 'perc', 'rim', 'cowbell'}
GM = {'kick': 36, 'snare': 38, 'clap': 39, 'hat': 42, 'ohat': 46, 'ride': 51, 'shaker': 70, 'perc': 45, 'rim': 37, 'cowbell': 56}
LENGTHS = {'short': 0.6, 'normal': 1.0, 'long': 1.4}

DEFAULTS = dict(genre='house', seed=1, bpm=None, key=None, energy=0.6, length='normal', part_seeds={}, title=None)


def kind_of(name):
    n = name.lower()
    for k, words in (('intro', ('intro',)), ('outro', ('outro', 'end')), ('build', ('build', 'rise', 'pre')),
                     ('drop', ('drop', 'chorus', 'hook', 'climax')), ('break', ('break', 'bridge', 'organ'))):
        if any(n.startswith(w) for w in words):
            return k
    return 'groove'


def _weighted(r, weights):
    items = list(weights.items())
    tot = sum(w for _, w in items)
    x = r.random() * tot
    for k, w in items:
        x -= w
        if x <= 0:
            return k
    return items[-1][0]


# ------------------------------------------------------------------ harmony
def progression(g, key, r, alt=False):
    h = g['harmony']
    loop = int(h.get('loop', 4))
    ok = lambda d: h.get('allow_dim') or key.quality(d) in ('maj', 'min')   # noqa: E731
    if h.get('static'):
        choices = [[0, 0], [0, 5], [0, 6], [0, 3], [0, 1]] if not alt else [[5, 6], [3, 4], [5, 5]]
        choices = [c for c in choices if all(ok(d) for d in c)] or [[0, 0]]
        p = r.choice(choices)
        return (p * loop)[:loop] if len(p) < loop else p
    moves = {int(k): {int(a): w for a, w in v.items()} for k, v in h['moves'].items()}
    best = None
    for _ in range(40):
        d = r.choice(h.get('start', [0])) if not alt else r.choice([5, 3, 2, 6])
        if not ok(d):
            d = 0
        p = [d]
        while len(p) < loop:
            opts = {a: w for a, w in moves.get(p[-1], {0: 1}).items() if ok(a)} or {0: 1}
            p.append(_weighted(r, opts))
        back = moves.get(p[-1], {}).get(p[0], 0)          # does the loop flow back into its start?
        distinct = len(set(p))
        rep = sum(1 for a, b in zip(p, p[1:]) if a == b)
        s = back * 0.6 + min(distinct, 4) * 1.0 - rep * 1.5 + r.random() * 0.5
        if best is None or s > best[0]:
            best = (s, p)
    return best[1]


def chord_pcs(key, deg, color, r):
    size = 3
    if r.random() < color:
        size = 4
    pcs = key.chord_pcs(deg, size)
    if r.random() < color * 0.5:
        pcs.append(key.pc(deg + 8))     # add 9
    return pcs


# ------------------------------------------------------------------ the composer
def compose(settings, locked=None, prev_harmony=None):
    s = dict(DEFAULTS, **{k: v for k, v in (settings or {}).items() if v is not None})
    g = G.load(s['genre'])
    gid = g['id']
    seed = int(s['seed'])
    ps = s.get('part_seeds') or {}
    locked = locked or {}

    def R(part):
        return rng(seed, gid, part, ps.get(part, 0))

    # ---- tempo and key
    lo, hi = g['bpm']
    bpm = float(s['bpm']) if s.get('bpm') else R('tempo').randint(lo, hi)
    for k in (2.0, 0.5):                       # a half- or double-time tempo for this genre is read as the real one
        if not (lo - 6 <= bpm <= hi + 6) and lo - 6 <= bpm * k <= hi + 6:
            bpm *= k
    pk = parse_key(s['key']) if s.get('key') else None
    if pk:
        key = Key(pk[0], pk[1])
    else:
        rk = R('key')
        root = rk.randrange(12)
        hint = s.get('scale_hint')
        key = Key(root, hint if hint in g['scales'] else _weighted(rk, g['scales']))
    energy_shift = (float(s['energy']) - 0.6) * 0.5

    # ---- form
    rf = R('form')
    form = rf.choice(g['forms'])
    scale = LENGTHS.get(s['length'], 1.0)
    sections, bar = [], 0
    for item in form:
        name, bars, e = item[0], item[1], item[2]
        step = 8 if bars >= 16 else 4
        nb = max(4, int(round(bars * scale / step)) * step)
        e2 = max(0.05, min(1.0, e + energy_shift))
        sections.append(Section(name, bar, nb, [kind_of(name), f'e{e2:.2f}']))
        bar += nb
    total_bars = bar
    sec_energy = [float(x.tags[1][1:]) for x in sections]

    # ---- harmony
    h = g['harmony']
    bpc = int(h.get('bars_per_chord', 1))
    rh = R('harmony')
    color = float(h.get('color', 0.3))
    if prev_harmony and 'harmony' not in ps:
        main, alt = prev_harmony['main'], prev_harmony['alt']
    else:
        main = progression(g, key, rh)
        alt = progression(g, key, rh, alt=True)
        lead_lock = next((v for k, v in locked.items() if k in ('lead',)), None)
        if lead_lock and not h.get('static'):
            cands = [progression(g, key, rng(seed, gid, 'harmony-fit', i)) for i in range(40)]
            main, fit = fit_to_locked(cands, [(b, l, m) for b, l, m, _ in lead_lock], key, bpc, len(cands[0]) * bpc)
    loop_bars = len(main) * bpc
    rc = R('voicing')
    pcs_main = [chord_pcs(key, d, color, rc) for d in main]
    pcs_alt = [chord_pcs(key, d, color, rc) for d in alt]

    def chord_of_bar(si, b_in):
        use_alt = sections[si].tags[0] == 'break' and not h.get('static') and g.get('break_alt', True)
        prog, pcs = (alt, pcs_alt) if use_alt else (main, pcs_main)
        i = (b_in // bpc) % len(prog)
        return prog[i], pcs[i]

    # ---- swing
    sw = float(g.get('swing', 0.5))
    unit = 0.25 if int(g.get('swing_unit', 16)) == 16 else 0.5

    def swing(beat):
        k = beat / unit
        if abs(k - round(k)) < 1e-6 and int(round(k)) % 2 == 1:
            return beat + (sw - 0.5) * 2 * unit
        return beat

    # ---- tracks
    tracks_spec = g['tracks']
    song = Song(title=s.get('title') or '', genre=gid, seed=seed, bpm=bpm, key=key.name(), sections=sections,
                settings=dict(s, genre=gid))
    kick_steps = {}               # (si, bar_in) -> set of 16th steps with a kick (for the bass to lock to)
    report = dict(genre=g['name'], bpm=bpm, key=key.name(), bars=total_bars,
                  progression=' – '.join(key.roman(d) for d in main),
                  break_progression=' – '.join(key.roman(d) for d in alt) if not h.get('static') else None,
                  form=[f'{x.name} {x.bars}' for x in sections])

    def active(t, si):
        e = sec_energy[si]
        k = sections[si].tags[0]
        if not (t.get('min', 0) <= e <= t.get('max', 1.01)):
            return False
        if k == 'build' and t['role'] in ('kick', 'bass') and not t.get('in_build'):
            return False
        if k == 'break' and t['role'] in ('kick', 'bass') and not t.get('in_break'):
            return False
        if t.get('only') and k not in t['only']:
            return False
        if t.get('not_in') and k in t['not_in']:
            return False
        return True

    def level_of(si):
        e = sec_energy[si]
        return 'low' if e < 0.5 else 'mid' if e < 0.8 else 'high'

    flags = g.get('drum_flags', {})
    human = float(flags.get('humanize', 0.2))
    out_notes = {}

    def add(tid, si, beat, dur, midi, vel, **p):
        out_notes.setdefault(tid, {}).setdefault(si, []).append((beat, dur, midi, vel, p))

    # drums first (the bass locks to the kick)
    order = sorted(tracks_spec, key=lambda t: 0 if t['role'] == 'kick' else 1 if t['role'] in DRUM_ROLES else 2)
    melody_info = {}
    for t in order:
        tid, role = t['id'], t['role']
        if tid in locked:
            continue
        rt = R('track-' + tid)
        if role in DRUM_ROLES:
            voice = t.get('voice', role)
            for si, sec in enumerate(sections):
                if not active(t, si):
                    continue
                kind = sec.tags[0]
                pats = g['drums'].get(level_of(si), {})
                pat = pats.get(voice)
                roll = kind == 'build' and flags.get('build_roll') == voice
                if pat is None and not roll:
                    continue
                for b in range(sec.bars):
                    last = b == sec.bars - 1 and si + 1 < len(sections)
                    nxt_kind = sections[si + 1].tags[0] if si + 1 < len(sections) else None
                    if roll:
                        prog = b / max(1, sec.bars)
                        div = 4 if prog < 0.25 else 8 if prog < 0.5 else 16 if prog < 0.85 else 32
                        n = div
                        for k in range(n):
                            beat = b * 4 + 4 * k / n
                            add(tid, si, beat, 0.1, GM.get(voice, 38), 0.35 + 0.65 * (b * 4 + 4 * k / n) / (sec.bars * 4))
                        continue
                    L = len(pat) // 16
                    bar_pat = pat[(b % L) * 16:(b % L) * 16 + 16]
                    if last and flags.get('fills') and voice in ('snare', 'clap') and kind != 'intro':
                        fill = rt.choice(['..x.xxxx', 'x.x.xxxx', '....xXxX', 'xxxxxxxx', '..xx..xX'])
                        bar_pat = bar_pat[:8] + fill
                    if last and voice == 'kick' and nxt_kind == 'drop':
                        bar_pat = bar_pat[:12] + '....'                 # a beat of silence before the drop
                    for st, c in enumerate(bar_pat):
                        if c not in VEL:
                            continue
                        v = VEL[c] * (1 + (rt.random() - 0.5) * 0.25 * human)
                        jitter = 0 if voice == 'kick' else (rt.random() - 0.5) * 0.02 * human
                        beat = swing(b * 4 + st * 0.25) + jitter
                        if voice == 'kick':
                            kick_steps.setdefault((si, b), set()).add(st)
                        add(tid, si, max(0.0, beat), 0.2, GM.get(voice, 38), max(0.1, min(1.0, v)))
                    if flags.get('hat_rolls') and voice == 'hat' and rt.random() < 0.55:
                        at = rt.choice([1.5, 2.5, 3.0, 3.5])
                        n = rt.choice([3, 4, 6])
                        span = 0.5
                        for k in range(n):
                            add(tid, si, b * 4 + at + span * k / n, 0.05, 42, 0.45 + 0.4 * k / n)
        elif role == 'bass':
            _bass(t, g, key, sections, active, chord_of_bar, kick_steps, swing, bpm, rt, add)
        elif role in ('chords', 'pad'):
            _chords(t, g, key, sections, active, chord_of_bar, swing, rt, add)
        elif role == 'arp':
            _arp(t, g, key, sections, active, chord_of_bar, rt, add)
        elif role == 'riff':
            _riff(t, g, key, sections, active, chord_of_bar, rt, add)
        elif role == 'lead':
            lg = g['lead']
            phrase_bars = 8 if loop_bars >= 4 and lg.get('bars', 8) == 8 else 4
            if loop_bars == 8:
                phrase_bars = 8

            def chord_deg_at(bar_in_phrase):
                return main[(bar_in_phrase // bpc) % len(main)]
            octave = int(lg.get('octave', 5))
            center = 7 * (octave - 4) + 4
            rm = R('melody')
            notes, info = write_hook(key, chord_deg_at, phrase_bars, lg['rhythms'], float(lg.get('density', 0.5)),
                                     center, rm, candidates=int(lg.get('candidates', 48)))
            melody_info = info
            verse = verse_variant(notes, chord_deg_at, rm)
            skel = skeleton(notes)
            for si, sec in enumerate(sections):
                if not active(t, si):
                    continue
                kind = sec.tags[0]
                if kind == 'break' and not lg.get('break_skeleton', True):
                    continue
                line = notes if kind in ('drop',) else skel if kind in ('break', 'build', 'intro', 'outro') else verse
                if kind == 'groove' and sec_energy[si] >= 0.8:
                    line = notes
                for rep in range(max(1, sec.bars // phrase_bars)):
                    for st, ln, d in line:
                        beat = rep * phrase_bars * 4 + st * 0.25
                        if beat >= sec.bars * 4:
                            continue
                        midi = key.midi(d, 4)
                        vel = 0.75 + (0.2 if st % 8 == 0 else 0) + (rt.random() - 0.5) * 0.1
                        add(tid, si, swing(beat), ln * 0.25 * 0.92, midi, min(1, vel))
        elif role == 'fx':
            for si, sec in enumerate(sections):
                kind = sec.tags[0]
                nxt = sections[si + 1].tags[0] if si + 1 < len(sections) else None
                if kind == 'build':
                    add(tid, si, 0.0, sec.bars * 4, 60, 0.8, kind='riser')
                if nxt == 'drop':
                    add(tid, si, sec.bars * 4 - 4, 4, 60, 0.7, kind='revcrash')
                if kind == 'drop':
                    add(tid, si, 0.0, 2, 60, 0.9, kind='impact')
                    add(tid, si, 0.0, 4, 60, 0.7, kind='crash')
                if kind == 'break' and si > 0 and sections[si - 1].tags[0] == 'drop':
                    add(tid, si, 0.0, 8, 60, 0.6, kind='downlifter')
    if g.get('vinyl'):
        for si, sec in enumerate(sections):
            add('vinyl', si, 0.0, sec.bars * 4, 60, 0.6, kind='vinyl')

    # ---- build the song document
    spec_by_id = {t['id']: t for t in tracks_spec}
    if g.get('vinyl'):
        spec_by_id['vinyl'] = dict(id='vinyl', role='fx', inst='fx', label='Vinyl')
    for tid, spec in spec_by_id.items():
        tr = Track(id=tid, role=spec['role'], instrument=spec['inst'],
                   params={k: spec[k] for k in ('rev', 'dly', 'sc', 'level', 'voice', 'label', 'width') if k in spec},
                   pan=float(spec.get('pan', 0.0)))
        if tid in locked:
            tr.locked = True
            by_sec = {}
            for (b, l, m, v) in locked[tid]:
                si = next((i for i, x in enumerate(sections) if x.start_bar * 4 <= b < (x.start_bar + x.bars) * 4), None)
                if si is not None:
                    by_sec.setdefault(si, []).append((b - sections[si].start_bar * 4, l, m, v, {}))
            notes_by_sec = by_sec
        else:
            notes_by_sec = out_notes.get(tid, {})
        for si, ns in sorted(notes_by_sec.items()):
            cid = f'{tid}@{si}'
            song.clips[cid] = Clip(cid, sections[si].bars * 4,
                                   [Note(round(b, 4), round(max(0.02, l), 4), int(m), round(float(v), 3), dict(p)) for b, l, m, v, p in ns])
            tr.placements.append(Placement(cid, si))
        if tr.placements or tid in locked:
            song.tracks.append(tr)
    report['melody'] = melody_info
    report['harmony'] = dict(main=main, alt=alt)
    song.settings['report'] = report
    song.settings['harmony'] = dict(main=main, alt=alt)
    if not song.title:
        song.title = make_title(gid, key, seed)
    return song


# ------------------------------------------------------------------ part writers
def _bass_midi(pc, lo=28, hi=43, near=34):
    cands = [m for m in range(lo, hi + 1) if m % 12 == pc]
    return min(cands, key=lambda m: abs(m - near))


def _bass(t, g, key, sections, active, chord_of_bar, kick_steps, swing, bpm, r, add):
    style = g['bass'].get('style', 'pulse8')
    tid = t['id']
    beat_s = 60 / bpm
    prev_midi = None
    for si, sec in enumerate(sections):
        if not active(t, si):
            continue
        for b in range(sec.bars):
            deg, pcs = chord_of_bar(si, b)
            root = _bass_midi(key.pc(deg))
            fifth = root + 7 if root + 7 <= 47 else root - 5
            nxt_deg, _ = chord_of_bar(si, b + 1) if b + 1 < sec.bars else (deg, pcs)
            nxt_root = _bass_midi(key.pc(nxt_deg))
            ks = kick_steps.get((si, b), {0, 4, 8, 12})
            B = b * 4

            def n(step, ln_steps, m, v=0.85, **p):
                add(tid, si, swing(B + step * 0.25), ln_steps * 0.25, m, v, **p)
            if style == 'offbeat':
                for st in (2, 6, 10, 14):
                    m = root + (12 if st == 14 and r.random() < 0.25 else 0)
                    n(st, 1.6, m, 0.9 if st != 14 else 0.8)
                if r.random() < 0.3:
                    n(15, 0.8, root + 12, 0.6)
            elif style == 'deep':
                pat = r.choice(['..x...x..x....x.', '..x...x...x..x..', '..x..x....x...x.'])
                on = [i for i, c in enumerate(pat) if c == 'x']
                for j, st in enumerate(on):
                    ln = (on[j + 1] if j + 1 < len(on) else 16) - st
                    m = root if r.random() < 0.75 else root + rr(r, [7, 12, 10])
                    n(st, ln * 0.8, m, 0.85)
            elif style in ('rolling', 'rumble'):
                for st in range(16):
                    if st in ks or st % 4 == 0:
                        continue
                    pop = style == 'rolling' and st % 4 == 2 and r.random() < 0.2
                    v = 0.85 if style == 'rolling' else 0.55 + 0.25 * (1 - (st % 4) / 4)
                    n(st, 0.85, root + (12 if pop else 0), v)
            elif style == 'gallop':
                for beat in range(4):
                    for k in (2, 3):
                        n(beat * 4 + k, 0.9, root, 0.85 if k == 2 else 0.7)
            elif style == 'pulse8':
                for st in range(0, 16, 2):
                    m = root + (12 if st in (6, 14) and r.random() < 0.3 else 0)
                    n(st, 1.7, m, 0.95 if st % 4 == 0 else 0.75)
            elif style == 'garage':
                pat = r.choice(['X..x...x.x..x...', 'X...x..x..x...x.', 'X..x..x...x..x..'])
                for st, c in enumerate(pat):
                    if c in 'Xx':
                        n(st, 1.6, root + (12 if c == 'x' and r.random() < 0.3 else 0), 0.95 if c == 'X' else 0.75)
            elif style == 'walk':
                n(0, 6, root, 0.9)
                n(6, 2, fifth, 0.7)
                if r.random() < 0.7:
                    n(10, 4, root + rr(r, [0, 12, 10]), 0.75)
                if nxt_root != root:
                    n(14, 2, nxt_root + (1 if nxt_root < root else -1), 0.65)
            elif style == 'hold':
                if b % 2 == 0:
                    n(0, 32, root, 0.8)
            elif style in ('sub_long', 'reese'):
                kicks = sorted(ks) or [0, 10]
                for j, st in enumerate(kicks):
                    end = kicks[j + 1] if j + 1 < len(kicks) else 16
                    m = root if j == 0 or r.random() < 0.6 else rr(r, [fifth, root + 12, root - 2 if root - 2 >= 28 else root])
                    n(st, (end - st) * 0.95, m, 0.9)
                if style == 'reese' and r.random() < 0.3:
                    n(14, 2, root + 12, 0.7)
            elif style == 'wobble':
                rates = [1, 2, 3, 4, 6]
                pat = r.choice(['X.......X...X...', 'X...X...X.x.X...', 'X.....X...X.X...', 'X.......X.......'])
                on = [i for i, c in enumerate(pat) if c in 'Xx']
                for j, st in enumerate(on):
                    ln = (on[j + 1] if j + 1 < len(on) else 16) - st
                    rate = round(rr(r, rates) / beat_s, 2)
                    m = root if r.random() < 0.7 else rr(r, [root + 12, fifth, root + 3])
                    n(st, ln * 0.95, m, 0.9, rate=rate)
            elif style == '808':
                kicks = sorted(ks) or [0]
                for j, st in enumerate(kicks):
                    end = kicks[j + 1] if j + 1 < len(kicks) else 16
                    m = root if r.random() < 0.65 else rr(r, [fifth, root + 12, root + 10 if root + 10 < 48 else root])
                    p = {}
                    if prev_midi is not None and abs(m - prev_midi) >= 5 and r.random() < 0.45:
                        p['from'] = round(440 * 2 ** ((prev_midi - 69) / 12), 2)
                    n(st, (end - st) * 0.98, m, 0.95, **p)
                    prev_midi = m
            elif style == 'acid':
                pent = [0, 3, 5, 7, 10]
                for st in range(16):
                    if r.random() < 0.28:
                        continue
                    off = rr(r, pent) + (12 if r.random() < 0.25 else 0)
                    acc = 1.0 if r.random() < 0.25 else 0.0
                    n(st, 0.9 if r.random() > 0.2 else 1.6, root + off, 0.8 + 0.2 * acc, accent=acc)
            elif style == 'dub':      # deep dubstep: long sub notes, half-step phrasing
                if b % 2 == 0:
                    n(0, 12, root, 0.9)
                    if r.random() < 0.6:
                        n(12, 4, rr(r, [root, root + 3, root - 2 if root - 2 >= 28 else root + 5]), 0.8)
                else:
                    n(0, 6, rr(r, [root, root + 7, root + 5]), 0.85)
                    n(8, 8, root, 0.85)
            else:
                n(0, 16, root, 0.85)


def rr(r, xs):
    return r.choice(xs)


def _chords(t, g, key, sections, active, chord_of_bar, swing, r, add):
    c = g['chords']
    tid = t['id']
    is_pad = t['role'] == 'pad'
    rhythm = 'hold' if is_pad else c.get('rhythm', 'hold')
    lo, hi = (c.get('octave_lo', 52), c.get('octave_hi', 76)) if not is_pad else (57, 84)
    strum = float(c.get('strum', 0.0))
    prev = None
    bpc = int(g['harmony'].get('bars_per_chord', 1))
    for si, sec in enumerate(sections):
        if not active(t, si):
            continue
        b = 0
        while b < sec.bars:
            deg, pcs = chord_of_bar(si, b)
            v = voice_lead(pcs, prev, lo, hi)
            prev = v
            span = bpc if rhythm == 'hold' else 1
            span = min(span, sec.bars - b)
            if rhythm == 'hold':
                for i, m in enumerate(v):
                    add(tid, si, b * 4 + i * strum, span * 4 - 0.05, m, 0.7 + r.random() * 0.1)
            else:
                ln = float(c.get('length', 0.4))
                for st, ch in enumerate(rhythm[:16]):
                    if ch not in 'Xxo':
                        continue
                    vel = {'X': 0.9, 'x': 0.75, 'o': 0.55}[ch]
                    for i, m in enumerate(v):
                        add(tid, si, swing(b * 4 + st * 0.25) + i * strum, ln, m, vel)
            b += span


def _arp(t, g, key, sections, active, chord_of_bar, r, add):
    a = g['arp']
    tid = t['id']
    rate = int(a.get('rate', 16))
    step = 4 / rate * 1.0 if rate else 0.25
    step = 1.0 / (rate / 4)
    octs = int(a.get('octaves', 2))
    gate = float(a.get('gate', 0.6))
    pattern = a.get('pattern', 'updown')
    for si, sec in enumerate(sections):
        if not active(t, si):
            continue
        for b in range(sec.bars):
            deg, pcs = chord_of_bar(si, b)
            base = sorted(set(60 + ((p - 60) % 12) for p in pcs))
            tones = [m + 12 * o for o in range(octs) for m in base]
            if pattern == 'updown':
                seq = tones + tones[-2:0:-1]
            elif pattern == 'random':
                seq = [r.choice(tones) for _ in range(16)]
            else:
                seq = tones
            n = int(4 / step)
            for k in range(n):
                m = seq[(b * n + k) % len(seq)]
                add(tid, si, b * 4 + k * step, step * gate, m, 0.8 if k % 4 == 0 else 0.62)


def _riff(t, g, key, sections, active, chord_of_bar, r, add):
    """A repeating riff from the pack: steps with semitone offsets from the chord root (chromatic allowed)."""
    rf = g.get('riff') or {}
    pats = rf.get('patterns') or [[[0, 0, 2], [2, 1, 2], [4, 0, 2], [6, -1, 2]]]
    pat = r.choice(pats)
    octave = int(t.get('octave', rf.get('octave', 2)))
    tid = t['id']
    for si, sec in enumerate(sections):
        if not active(t, si):
            continue
        for b in range(sec.bars):
            deg, pcs = chord_of_bar(si, b)
            root = 12 * (octave + 1) + key.pc(deg)
            for st, off, ln in pat:
                add(tid, si, b * 4 + st * 0.25, ln * 0.25 * 0.95, root + off, 0.9 if st % 4 == 0 else 0.75)


# ------------------------------------------------------------------ titles
_WORDS = {
    'a': ['Neon', 'Midnight', 'Golden', 'Silver', 'Lunar', 'Velvet', 'Static', 'Hollow', 'Electric', 'Distant', 'Quiet', 'Crystal',
          'Echo', 'Paper', 'Glass', 'Signal', 'Northern', 'Faded', 'Solar', 'Analog'],
    'b': ['Horizon', 'Tides', 'Machine', 'Garden', 'Signal', 'Rooftops', 'Satellite', 'Haze', 'Pulse', 'Avenue', 'Coast', 'Drift',
          'Lights', 'Memory', 'Engine', 'Frequency', 'Harbor', 'Orbit', 'Fields', 'Ghosts'],
}


def make_title(gid, key, seed):
    r = rng(seed, gid, 'title')
    return f"{r.choice(_WORDS['a'])} {r.choice(_WORDS['b'])}"


def song_beats_notes(song, track_id):
    """[(beat, len, midi, vel)] in song beats for a track (used for locking)."""
    return [(n.beat, n.length, n.pitch, n.velocity) for n in song.notes_of(track_id)]


def key_names():
    return NOTE_NAMES


def seconds(song):
    return song.total_bars() * 4 * 60 / song.bpm


def bars_to_sec(bpm, bars):
    return bars * 4 * 60 / bpm


__all__ = ['compose', 'kind_of', 'song_beats_notes', 'seconds', 'math']
