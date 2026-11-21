"""The composer: settings + a genre pack -> a Song document (sections, tracks, notes) and a short report.

Every random choice has its own generator seeded by (seed, genre, part), so:
  - the same seed in two genres gives two unrelated songs (different keys, tempos, progressions);
  - re-rolling one part (settings['part_seeds']) changes only that part.
Locked tracks (locked={track_id: [(beat, len, midi, vel)]}) are kept note for note; if the harmony is re-rolled under
a locked melody, the new chord loop is chosen to fit that melody.

What keeps a song from being a loop (2.1):
  phrase variation   the 4th, 8th and 16th bars of a phrase change a little: small fills, hats that drop out or open,
                     a skipped kick, ghost snares; fills are no longer only at the end of a section
  entries and exits  in intros parts come in on the 8-bar grid instead of all at once; in outros they leave one by one
  sweeps             filter automation: intros open up, builds thin out from the bottom, breakdowns bloom
  later drops        the second and later drops change: the lead doubles an octave up, an extra layer joins, and in
                     some genres the final drop lifts the key
  call and response  a second sound answers the lead in the gaps it leaves
  harmony colour     a major V in minor keys (the leading tone pulls home), a borrowed minor iv in major keys,
                     chords that arrive an 8th early, bass notes that walk into the next chord
"""
import math

from . import genres as G
from .melody import (answer_phrase, fit_to_locked, refit, skeleton, verse_variant, write_chops, write_hook,
                     write_ostinato)
from .song import Clip, Note, Placement, Section, Song, Track
from .theory import Key, NOTE_NAMES, color_pcs, declutter, parse_key, rng, voice_lead

VEL = {'X': 1.0, 'x': 0.78, 'o': 0.55, 'g': 0.32}
DRUM_ROLES = {'kick', 'snare', 'clap', 'hat', 'ohat', 'ride', 'shaker', 'perc', 'rim', 'cowbell'}
PITCHED_ROLES = {'bass', 'riff', 'chords', 'pad', 'arp', 'lead', 'answer'}
GM = {'kick': 36, 'snare': 38, 'clap': 39, 'hat': 42, 'ohat': 46, 'ride': 51, 'shaker': 70, 'perc': 45, 'rim': 37, 'cowbell': 56}
LENGTHS = {'short': 0.6, 'normal': 1.0, 'long': 1.4, 'extended': 1.8, 'loop': 1.0}
VARIATION = {'low': 0.35, 'normal': 1.0, 'high': 1.6}
FILL_P = {'none': 0.0, 'fewer': 0.35, 'normal': 0.75, 'more': 1.0}
GHOST_P = {'off': 0.0, 'normal': 0.05, 'more': 0.15}
APPROACH_STYLES = {'offbeat', 'pulse8', 'garage', 'gallop', 'deep', 'sub_long', 'reese', 'rolling', 'rumble'}

DEFAULTS = dict(genre='house', seed=1, bpm=None, key=None, energy=0.6, length='normal', part_seeds={}, title=None,
                fills='normal', hats='normal', ghosts='normal', builds='on', fx='normal', variation='normal')
CHOICES = dict(length=list(LENGTHS), fills=list(FILL_P), hats=['sparse', 'normal', 'busy'], ghosts=list(GHOST_P),
               builds=['on', 'subtle', 'off'], fx=['normal', 'fewer', 'off'], variation=list(VARIATION))


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


def _merge(base, over):
    """Overlay a drum figure: every non-'.' character of `over` replaces the one in `base` (same length)."""
    return ''.join(o if o != '.' else b for b, o in zip(base, over))


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


def _alterations(g, key, prog, r):
    """Per chord of a loop: {pitch class: new pitch class}. A major V in minor / dorian (raised leading tone), and a
    borrowed minor iv in major. Chosen once per song so the colour is consistent."""
    h = g['harmony']
    out = [dict() for _ in prog]
    if h.get('static'):
        return out
    if key.scale_name in ('minor', 'dorian') and r.random() < float(h.get('dominant', 0.5)):
        lt = key.pc(6)
        for i, d in enumerate(prog):
            if d % 7 == 4:
                out[i] = {lt: (lt + 1) % 12}
    if key.scale_name == 'major' and r.random() < float(h.get('borrow', 0.3)):
        idx = [i for i, d in enumerate(prog) if d % 7 == 3]
        if idx:
            six = key.pc(5)
            out[idx[-1]] = {six: (six - 1) % 12}
    return out


def _label(key, deg, pcs):
    r = key.roman(deg)
    if len(pcs) >= 2 and key.quality(deg % 7) in ('maj', 'min'):
        major = (pcs[1] - pcs[0]) % 12 == 4
        r = r.upper() if major else r.lower()
    return r


# ------------------------------------------------------------------ the composer
def compose(settings, locked=None, prev_harmony=None):
    s = dict(DEFAULTS, **{k: v for k, v in (settings or {}).items() if v is not None})
    for k, opts in CHOICES.items():
        if s.get(k) not in opts:
            s[k] = DEFAULTS[k]
    g = G.load(s['genre'])
    gid = g['id']
    seed = int(s['seed'])
    ps = s.get('part_seeds') or {}
    locked = locked or {}
    var = VARIATION[s['variation']]

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

    # ---- form (a layout edited in the section editor wins: settings['form_override'] = [[name, bars, energy], ...])
    rf = R('form')
    form = rf.choice(g['forms'])
    override = s.get('form_override')
    if override:
        sections, bar = [], 0
        for name, bars, e in override:
            nb = max(1, int(bars))
            sections.append(Section(str(name), bar, nb, [kind_of(str(name)), f'e{float(e):.2f}', f'b{float(e):.2f}']))
            bar += nb
    if s['builds'] == 'off':
        form = [it for it in form if kind_of(it[0]) != 'build'] or form
    if s['length'] == 'loop':
        best = max(form, key=lambda it: (kind_of(it[0]) == 'drop', it[2]))
        form = [[best[0], 16, best[2]]]
    scale = LENGTHS.get(s['length'], 1.0)
    if not override:
        sections, bar = [], 0
        for item in form:
            name, bars, e = item[0], item[1], item[2]
            step = 8 if bars >= 16 else 4
            nb = 16 if s['length'] == 'loop' else max(4, int(round(bars * scale / step)) * step)
            e2 = max(0.05, min(1.0, e + energy_shift))
            sections.append(Section(name, bar, nb, [kind_of(name), f'e{e2:.2f}', f'b{e2:.2f}']))
            bar += nb
    total_bars = bar
    mutes = {int(k): set(v) for k, v in (s.get('section_mutes') or {}).items()}

    # ---- later drops: what changes
    rd = R('drop2')
    drops = [i for i, x in enumerate(sections) if x.tags[0] == 'drop']
    opts = list(g.get('drop2', ['lead_octave', 'layer']))
    drop_changes = {}
    for k, si in enumerate(drops[1:], 1):
        n = 0 if var < 0.5 else 2 if var > 1.2 else 1
        pool = [o for o in opts if o != 'lift']
        ch = rd.sample(pool, min(n, len(pool)))
        if 'lift' in opts and si == drops[-1] and var >= 0.5 and rd.random() < float(g.get('lift_chance', 0.7)):
            ch.append('lift')
        drop_changes[si] = ch
    for si, ch in drop_changes.items():
        if 'layer' in ch:
            e = min(1.0, float(sections[si].tags[1][1:]) + 0.1)
            sections[si].tags[1] = f'e{e:.2f}'
    sec_energy = [float(x.tags[1][1:]) for x in sections]
    lift_si = next((si for si, ch in drop_changes.items() if 'lift' in ch), None)
    lift = rd.choice([1, 2]) if lift_si is not None else 0

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
    colour = {}                                   # one colour per chord degree, for the whole song

    def pcs_of(d):
        if d not in colour:
            size = 4 if rc.random() < color else 3
            colour[d] = color_pcs(key, d, size, rc.random() < color * 0.5)
        return list(colour[d][0])
    ra_h = R('harmony-colour')
    alts_main = _alterations(g, key, main, ra_h)
    alts_alt = _alterations(g, key, alt, ra_h)
    pcs_main = [[a.get(p, p) for p in pcs_of(d)] for d, a in zip(main, alts_main)]
    pcs_alt = [[a.get(p, p) for p in pcs_of(d)] for d, a in zip(alt, alts_alt)]
    use_break_alt = not h.get('static') and g.get('break_alt', True)

    def _prog(si):
        if sections[si].tags[0] == 'break' and use_break_alt:
            return alt, pcs_alt, alts_alt
        return main, pcs_main, alts_main

    def chord_of_bar(si, b_in):
        prog, pcs, _ = _prog(si)
        i = (b_in // bpc) % len(prog)
        return prog[i], pcs[i]

    def alter_of_bar(si, b_in):
        prog, _, alts = _prog(si)
        return alts[(b_in // bpc) % len(prog)]

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
                  progression=' – '.join(_label(key, d, p) for d, p in zip(main, pcs_main)),
                  break_progression=' – '.join(_label(key, d, p) for d, p in zip(alt, pcs_alt)) if use_break_alt else None,
                  form=[f'{x.name} {x.bars}' for x in sections])

    def active(t, si):
        e = sec_energy[si]
        k = sections[si].tags[0]
        if not (t.get('min', 0) <= e <= t.get('max', 1.01)):
            return False
        if k == 'build' and t['role'] in ('kick', 'bass') and not t.get('in_build') and s['builds'] != 'subtle':
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

    # ---- entries and exits: parts come in on the 8-bar grid in intros, leave one by one in outros
    win = {}                                      # (track id, section) -> (first beat, end beat) within the section
    if var >= 0.5 and s['length'] != 'loop':
        ra = R('arrange')
        for si, sec in enumerate(sections):
            k = sec.tags[0]
            act = [t for t in tracks_spec if t['role'] != 'fx' and t['id'] not in locked and active(t, si)]
            grid = list(range(0, sec.bars, 4 if sec.bars <= 8 else 8))
            if len(grid) < 2 or len(act) < 3:
                continue
            if k == 'intro':
                first = [t for t in act if t['role'] == 'kick'] or [t for t in act if t['role'] == 'pad'] or act[:1]
                rest = [t for t in act if t not in first]
                keep = ra.choice(rest)
                for t in rest:
                    if t is keep:
                        continue
                    e0 = ra.choice(grid[1:])
                    win[(t['id'], si)] = (e0 * 4, sec.bars * 4)
            elif k == 'outro':
                for t in act:
                    if t['role'] in ('kick', 'pad') or ra.random() > 0.6:
                        continue
                    win[(t['id'], si)] = (0, ra.choice(grid[1:]) * 4)
            elif k == 'groove' and sec.bars >= 16 and si > 0 and sections[si - 1].tags[0] == 'intro':
                late = [t for t in act if t['role'] in ('arp', 'lead', 'answer', 'perc', 'shaker', 'ohat', 'ride', 'chords')]
                if late:
                    t = ra.choice(late)
                    win[(t['id'], si)] = (sec.bars // 2 * 4, sec.bars * 4)

    flags = g.get('drum_flags', {})
    human = float(flags.get('humanize', 0.2))
    push = flags.get('push', {})
    hat_acc = flags.get('hat_accent', [1.0, 0.82, 0.92, 0.85])
    fill_p = FILL_P[s['fills']]
    ghost_p = GHOST_P[s['ghosts']] * (var if s['ghosts'] == 'normal' else 1)
    out_notes = {}

    def add(tid, si, beat, dur, midi, vel, **p):
        if tid in mutes.get(si, ()):
            return False
        w = win.get((tid, si))
        if w:
            if not (w[0] - 1e-6 <= beat < w[1]):
                return False
            dur = min(dur, w[1] - beat)
        out_notes.setdefault(tid, {}).setdefault(si, []).append((beat, dur, midi, vel, p))
        return True

    # drums first (the bass locks to the kick); the answer comes after the lead it answers
    def _order(t):
        return 0 if t['role'] == 'kick' else 1 if t['role'] in DRUM_ROLES else 3 if t['role'] == 'answer' else 2
    order = sorted(tracks_spec, key=_order)
    melody_info = {}
    lead_lines = {}
    lead_spec = next((t for t in tracks_spec if t['id'] == 'lead'), None)
    for t in order:
        tid, role = t['id'], t['role']
        if tid in locked:
            continue
        rt = R('track-' + tid)
        if role in DRUM_ROLES:
            _drums(t, g, s, sections, active, level_of, flags, human, push, hat_acc, fill_p, ghost_p, var, swing,
                   kick_steps, rt, add)
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
            style = t.get('device') or lg.get('style', 'hook')
            if style == 'chops':
                notes, info = write_chops(key, chord_deg_at, phrase_bars, center, rm)
            elif style == 'ostinato':
                notes, info = write_ostinato(key, chord_deg_at, phrase_bars, center, rm)
            else:
                notes, info = write_hook(key, chord_deg_at, phrase_bars, lg['rhythms'], float(lg.get('density', 0.5)),
                                         center, rm, candidates=int(lg.get('candidates', 48)),
                                         tension=float(lg.get('tension', 0.18)))
            if not melody_info or tid == 'lead':
                melody_info = info
            lead_lines[tid] = (notes, phrase_bars)
            verse = verse_variant(notes, chord_deg_at, rm) if style == 'hook' else notes
            skel = skeleton(notes) if style == 'hook' else notes
            for si, sec in enumerate(sections):
                if not active(t, si):
                    continue
                kind = sec.tags[0]
                if kind == 'break' and not lg.get('break_skeleton', True) and t.get('line') != 'hook':
                    continue
                line = notes if kind in ('drop',) else skel if kind in ('break', 'build', 'intro', 'outro') else verse
                if kind == 'groove' and sec_energy[si] >= 0.8:
                    line = notes
                if t.get('line') == 'hook':
                    line = notes
                doubled = tid == 'lead' and 'lead_octave' in drop_changes.get(si, ())
                soft = 0.85 if t.get('line') == 'hook' and kind == 'break' else 1.0
                _place_line(tid, si, sec, line, phrase_bars, key, chord_of_bar, swing, rt, add,
                            vel_scale=soft, double=doubled)
        elif role == 'answer':
            src = lead_lines.get(t.get('answers', 'lead'))
            if not src or lead_spec is None:
                continue
            notes, phrase_bars = src
            reg = int(t.get('register', -7))
            for si, sec in enumerate(sections):
                kind = sec.tags[0]
                if not active(t, si) or not active(lead_spec, si):
                    continue
                if not (kind == 'drop' or (kind == 'groove' and sec_energy[si] >= 0.8)):
                    continue
                ans = answer_phrase(notes, phrase_bars, None, rt, register=reg)
                _place_line(tid, si, sec, ans, phrase_bars, key, chord_of_bar, swing, rt, add, vel_scale=0.8)
        elif role == 'fx':
            if s['fx'] == 'off':
                continue
            fewer = s['fx'] == 'fewer'
            for si, sec in enumerate(sections):
                kind = sec.tags[0]
                nxt = sections[si + 1].tags[0] if si + 1 < len(sections) else None
                if kind == 'build' and s['builds'] == 'on':
                    add(tid, si, 0.0, sec.bars * 4, 60, 0.8, kind='riser')
                if nxt == 'drop' and not fewer:
                    add(tid, si, sec.bars * 4 - 4, 4, 60, 0.7, kind='revcrash')
                if kind == 'drop':
                    add(tid, si, 0.0, 2, 60, 0.9, kind='impact')
                    if not fewer:
                        add(tid, si, 0.0, 4, 60, 0.7, kind='crash')
                if kind == 'break' and si > 0 and sections[si - 1].tags[0] == 'drop' and not fewer:
                    add(tid, si, 0.0, 8, 60, 0.6, kind='downlifter')
    if g.get('vinyl'):
        for si, sec in enumerate(sections):
            add('vinyl', si, 0.0, sec.bars * 4, 60, 0.6, kind='vinyl')

    # ---- harmony colour and key lift. Chords, pads and arps are built from the altered chord tones already (and a
    # chord pushed in early starts inside the bar before it), so only the lines - lead, answer, bass, riff - are fitted.
    role_of = {t['id']: t['role'] for t in tracks_spec}
    for tid, by_sec in out_notes.items():
        if role_of.get(tid) not in PITCHED_ROLES:
            continue
        line = role_of.get(tid) in ('lead', 'answer', 'bass', 'riff')
        for si, ns in by_sec.items():
            up = lift if lift_si is not None and si >= lift_si else 0
            fixed = []
            for (b, l, m, v, p) in ns:
                amap = alter_of_bar(si, int(max(0.0, b + 0.01) // 4)) if line else None
                if amap and m % 12 in amap:
                    m += ((amap[m % 12] - m % 12 + 6) % 12) - 6
                fixed.append((b, l, m + up, v, p))
            by_sec[si] = fixed
    if lift:
        report['key_lift'] = f'+{lift} semitone{"s" if lift > 1 else ""} from {sections[lift_si].name} (bar {sections[lift_si].start_bar + 1})'
    report['later_drops'] = {f'{sections[si].name} @ bar {sections[si].start_bar + 1}': ch for si, ch in drop_changes.items() if ch}

    # ---- filter sweeps (automation): intros open, builds thin out from below, breakdowns bloom
    auto = {}
    if g.get('sweeps', True) and var >= 0.5 and s['length'] != 'loop':
        for si, sec in enumerate(sections):
            k = sec.tags[0]
            b0, b1 = sec.start_bar * 4, (sec.start_bar + sec.bars) * 4
            for t in tracks_spec:
                if t['id'] in locked or not active(t, si):
                    continue
                r_ = t['role']
                if k == 'intro' and sec.bars >= 8 and r_ in ('chords', 'pad', 'arp', 'lead', 'answer', 'riff'):
                    auto.setdefault(t['id'], {}).setdefault('lp', []).append([b0, b1, 500.0, 16000.0])
                elif k == 'build' and s['builds'] == 'on' and r_ in ('chords', 'pad', 'arp', 'lead', 'answer', 'riff', 'bass'):
                    auto.setdefault(t['id'], {}).setdefault('hp', []).append([b0, b1, 30.0, 150.0 if r_ == 'bass' else 450.0])
                elif (k == 'break' and sec.bars >= 8 and si > 0 and sections[si - 1].tags[0] == 'drop'
                      and r_ in ('chords', 'pad')):
                    auto.setdefault(t['id'], {}).setdefault('lp', []).append([b0, b0 + (b1 - b0) * 0.75, 1200.0, 14000.0])

    # ---- build the song document
    spec_by_id = {t['id']: t for t in tracks_spec}
    if g.get('vinyl'):
        spec_by_id['vinyl'] = dict(id='vinyl', role='fx', inst='fx', label='Vinyl')
    for tid, spec in spec_by_id.items():
        tr = Track(id=tid, role=spec['role'], instrument=spec['inst'],
                   params={k: spec[k] for k in ('rev', 'dly', 'sc', 'level', 'voice', 'label', 'width', 'fx') if k in spec},
                   pan=float(spec.get('pan', 0.0)), automation=auto.get(tid, {}))
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
def _place_line(tid, si, sec, line, phrase_bars, key, chord_of_bar, swing, r, add, vel_scale=1.0, double=False):
    """Tile a phrase over a section (a partial last phrase is cut, never left silent), each repeat fitted to the
    chords that sound under it (a breakdown may run a different progression)."""
    end = sec.bars * 4
    for rep in range(max(1, math.ceil(sec.bars / phrase_bars))):
        bar0 = rep * phrase_bars
        fitted = refit(line, lambda b: chord_of_bar(si, bar0 + b)[0], lambda b: chord_of_bar(si, bar0 + b)[1], key)
        for st, ln, d in fitted:
            beat = bar0 * 4 + st * 0.25
            if beat >= end:
                continue
            dur = min(ln * 0.25 * 0.92, end - beat)
            midi = key.midi(d, 4)
            vel = (0.75 + (0.2 if st % 8 == 0 else 0) + (r.random() - 0.5) * 0.1) * vel_scale
            add(tid, si, swing(beat), dur, midi, min(1, vel))
            if double:
                add(tid, si, swing(beat), dur, midi + 12 if midi + 12 <= 96 else midi - 12, min(1, vel) * 0.55)


def _drums(t, g, s, sections, active, level_of, flags, human, push, hat_acc, fill_p, ghost_p, var, swing, kick_steps, rt, add):
    tid, role = t['id'], t['role']
    voice = t.get('voice', role)
    for si, sec in enumerate(sections):
        if not active(t, si):
            continue
        kind = sec.tags[0]
        pats = g['drums'].get(level_of(si), {})
        pat = pats.get(voice)
        roll = kind == 'build' and flags.get('build_roll') == voice and s['builds'] == 'on'
        if pat is None and not roll:
            continue
        nxt_kind = sections[si + 1].tags[0] if si + 1 < len(sections) else None
        for b in range(sec.bars):
            last = b == sec.bars - 1 and si + 1 < len(sections)
            if roll:
                prog = b / max(1, sec.bars)
                div = 4 if prog < 0.25 else 8 if prog < 0.5 else 16 if prog < 0.85 else 32
                for k in range(div):
                    beat = b * 4 + 4 * k / div
                    add(tid, si, beat, 0.1, GM.get(voice, 38), 0.35 + 0.65 * beat / (sec.bars * 4))
                continue
            L = len(pat) // 16
            bar_pat = pat[(b % L) * 16:(b % L) * 16 + 16]
            end8 = (b + 1) % 8 == 0 and not last
            end4 = (b + 1) % 4 == 0 and not end8 and not last
            # fills: at the end of the section, and smaller ones at the end of 8-bar phrases
            if voice in ('snare', 'clap') and kind != 'intro' and flags.get('fills', True):
                if last and fill_p > 0 and (fill_p >= 1 or rt.random() < fill_p + 0.2):
                    fill = rt.choice(['..x.xxxx', 'x.x.xxxx', '....xXxX', 'xxxxxxxx', '..xx..xX'])
                    if s['fills'] == 'more' and rt.random() < 0.5:
                        bar_pat = bar_pat[:4] + 'x.x.' + fill
                    else:
                        bar_pat = bar_pat[:8] + fill
                elif end8 and kind != 'outro' and rt.random() < fill_p * 0.75 * var:
                    bar_pat = bar_pat[:12] + _merge(bar_pat[12:], rt.choice(['..x.', '.x.x', '..xx', 'x.xx', '...x']))
            if voice == 'kick':
                if last and nxt_kind == 'drop':
                    bar_pat = bar_pat[:12] + '....'                 # a beat of silence before the drop
                elif (b + 1) % 16 == 0 and not last and kind == 'drop' and rt.random() < 0.3 * var:
                    bar_pat = bar_pat[:14] + '..'                   # a skipped kick at the end of a 16-bar phrase
            if voice in ('hat', 'shaker', 'ride'):
                if (end4 or end8) and rt.random() < 0.45 * var:
                    bar_pat = bar_pat[:14] + rt.choice(['..', '.x', 'xx', 'gx', 'x.'])
                if s['hats'] == 'sparse':
                    bar_pat = ''.join(c if i % 2 == 0 else '.' for i, c in enumerate(bar_pat))
                elif s['hats'] == 'busy':
                    bar_pat = ''.join('g' if c == '.' and i % 2 == 1 and rt.random() < 0.5 else c for i, c in enumerate(bar_pat))
            if voice == 'snare' and ghost_p > 0 and kind not in ('intro', 'outro'):
                bar_pat = ''.join('g' if c == '.' and i % 2 == 1 and rt.random() < ghost_p else c for i, c in enumerate(bar_pat))
            off = float(push.get(voice, 0.0))
            for st, c in enumerate(bar_pat):
                if c not in VEL:
                    continue
                v = VEL[c] * (1 + (rt.random() - 0.5) * 0.25 * human)
                if voice in ('hat', 'shaker', 'ride'):
                    v *= hat_acc[st % len(hat_acc)]
                jitter = 0 if voice == 'kick' else (rt.random() - 0.5) * 0.02 * human
                beat = swing(b * 4 + st * 0.25) + jitter + off
                if add(tid, si, max(0.0, beat), 0.2, GM.get(voice, 38), max(0.1, min(1.0, v))) and voice == 'kick':
                    kick_steps.setdefault((si, b), set()).add(st)
            if flags.get('hat_rolls') and voice == 'hat' and s['hats'] != 'sparse' and rt.random() < 0.55:
                at = rt.choice([1.5, 2.5, 3.0, 3.5])
                n = rt.choice([3, 4, 6])
                for k in range(n):
                    add(tid, si, b * 4 + at + 0.5 * k / n, 0.05, 42, 0.45 + 0.4 * k / n)


def _bass_midi(pc, lo=28, hi=43, near=34):
    cands = [m for m in range(lo, hi + 1) if m % 12 == pc]
    return min(cands, key=lambda m: abs(m - near))


def _bass(t, g, key, sections, active, chord_of_bar, kick_steps, swing, bpm, r, add):
    style = g['bass'].get('style', 'pulse8')
    approach_p = float(g['bass'].get('approach', 0.35)) if style in APPROACH_STYLES else 0.0
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
            buf = []

            def n(step, ln_steps, m, v=0.85, **p):
                buf.append([step, ln_steps, m, v, p])
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
            # walk into the next chord: the bar's last note becomes a scale step next to the coming root
            if approach_p and nxt_root != root and buf and r.random() < approach_p:
                nd = key.degree_of(nxt_root)
                if nd is not None:
                    step_deg = nd - 1 if nxt_root > root else nd + 1
                    target = min((m for m in range(26, 48) if m % 12 == key.pc(step_deg)), key=lambda m: abs(m - nxt_root))
                    lastn = max(buf, key=lambda x: x[0])
                    if lastn[0] >= 12:
                        lastn[2] = target
                        lastn[1] = min(lastn[1], 16 - lastn[0])
                    else:
                        lastn[1] = min(lastn[1], 14 - lastn[0])
                        buf.append([14, 2, target, 0.75, {}])
            B = b * 4
            for st, ln, m, v, p in buf:
                add(tid, si, swing(B + st * 0.25), ln * 0.25, m, v, **p)


def rr(r, xs):
    return r.choice(xs)


def _chords(t, g, key, sections, active, chord_of_bar, swing, r, add):
    c = g['chords']
    tid = t['id']
    is_pad = t['role'] == 'pad'
    rhythm = 'hold' if is_pad else c.get('rhythm', 'hold')
    lo, hi = (c.get('octave_lo', 52), c.get('octave_hi', 76)) if not is_pad else (57, 84)
    strum = float(c.get('strum', 0.0))
    push = float(c.get('push', 0.0))            # chords that arrive an 8th early (house, trance)
    prev = None
    bpc = int(g['harmony'].get('bars_per_chord', 1))
    for si, sec in enumerate(sections):
        if not active(t, si):
            continue
        spans = []
        b = 0
        while b < sec.bars:
            deg, pcs = chord_of_bar(si, b)
            core = set(pcs[:3])
            v = declutter(voice_lead(pcs, prev, lo, hi), core, hi)
            prev = v
            span = bpc if rhythm == 'hold' else 1
            span = min(span, sec.bars - b)
            spans.append((b, span, deg, v))
            b += span
        for i, (b, span, deg, v) in enumerate(spans):
            if rhythm == 'hold':
                early = push if i > 0 and deg != spans[i - 1][2] else 0.0
                late = push if i + 1 < len(spans) and spans[i + 1][2] != deg else 0.0
                for j, m in enumerate(v):
                    add(tid, si, b * 4 - early + j * strum, span * 4 - 0.05 + early - late, m, 0.7 + r.random() * 0.1)
            else:
                ln = float(c.get('length', 0.4))
                for st, ch in enumerate(rhythm[:16]):
                    if ch not in 'Xxo':
                        continue
                    vel = {'X': 0.9, 'x': 0.75, 'o': 0.55}[ch]
                    for j, m in enumerate(v):
                        add(tid, si, swing(b * 4 + st * 0.25) + j * strum, ln, m, vel)


def _arp(t, g, key, sections, active, chord_of_bar, r, add):
    a = g['arp']
    tid = t['id']
    rate = int(a.get('rate', 16))
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


__all__ = ['compose', 'kind_of', 'song_beats_notes', 'seconds', 'math', 'CHOICES']
