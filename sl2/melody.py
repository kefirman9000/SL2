"""Melody writing: plan a phrase from a motif, write many candidates, keep the one a critic likes best.

A hook is built like a songwriter would: a 2-bar motif (rhythm + shape), repeated on the next chords as a sequence,
then an answer that cadences on a stable note. The critic checks what makes a line singable:
  chord tones on strong beats, mostly steps with a few leaps (leaps recover in the other direction),
  a sensible range, one high point late in the phrase, an ending on the root or third, no long same-note runs.
Variants for other sections reuse the motif: the verse line is lower and thinner, the breakdown keeps the skeleton.
"""
from .theory import Key

STEPS_PER_BAR = 16


def _cells(rhythms, density, rnd):
    """Pick a motif rhythm (2 bars, 32 steps) and an answer rhythm, leaning sparse or busy with density."""
    scored = sorted(rhythms, key=lambda r: r.count('x') + r.count('X'))
    k = len(scored)
    lo = int(max(0, min(k - 1, round((density - 0.25) * k))))
    pool = scored[max(0, lo - 1):lo + 2] or scored
    a = rnd.choice(pool)
    b = rnd.choice([r for r in scored if r != a] or scored)
    return a, b


def _onsets(cell):
    return [i for i, c in enumerate(cell) if c in 'xX']


def chord_degrees(chord_deg, size=3):
    return {(chord_deg + 2 * i) % 7 for i in range(size)}


def _place(cell, bar0):
    """Onset steps of a 2-bar cell placed at bar0 -> [(abs_step, len_steps)]."""
    on = _onsets(cell)
    out = []
    for j, s in enumerate(on):
        nxt = on[j + 1] if j + 1 < len(on) else len(cell)
        out.append((bar0 * STEPS_PER_BAR + s, max(1, min(nxt - s, 8))))
    return out


def _candidate(key, chord_at, bars, cells, center, rnd, tension=0.18):
    """One melody: list of (step, len, degree). tension: chance of an appoggiatura on a strong beat."""
    a, b = cells
    plan = []
    if bars <= 4:
        plan = [('A', 0), ('B', 2)] if bars == 4 else [('A', 0)]
    else:
        plan = [('A', 0), ('A2', 2), ('A', 4), ('B', 6)]
    contour = rnd.choice(['arch', 'rise', 'wave', 'fall'])
    motif = None          # (intervals between notes, first-note chord-tone index)
    notes = []
    prev = center
    for part, bar0 in plan:
        cell = a if part.startswith('A') else b
        slots = _place(cell, bar0)
        if part.startswith('A') and motif is not None:
            ivs, _ = motif
            cdeg = chord_at(bar0)
            tones = sorted(chord_degrees(cdeg))
            # restate the motif starting from the chord tone nearest the last note (a sequence)
            start = min((t + 7 * o for t in tones for o in range(-2, 3)), key=lambda d: abs(d - prev))
            if part == 'A2':
                start += rnd.choice([0, 1, 2, -1])
            d = start
            line = [d]
            for iv in ivs[:len(slots) - 1]:
                d += iv
                line.append(d)
            while len(line) < len(slots):
                line.append(line[-1] + rnd.choice([-1, 1]))
            for (st, ln), dg in zip(slots, line):
                bar = st // STEPS_PER_BAR
                if st % 8 == 0 and dg % 7 not in chord_degrees(chord_at(bar)):
                    dg = min((t + 7 * o for t in chord_degrees(chord_at(bar)) for o in range(-2, 4)), key=lambda x: abs(x - dg))
                notes.append((st, ln, dg))
            prev = notes[-1][2]
            continue
        # new material (the motif itself, or the answer)
        line = []
        n = len(slots)
        resolve = None
        for i, (st, ln) in enumerate(slots):
            bar = st // STEPS_PER_BAR
            cd = chord_at(bar)
            tones = chord_degrees(cd)
            x = i / max(1, n - 1)
            shape = {'arch': 1 - abs(2 * x - 1), 'rise': x, 'fall': 1 - x, 'wave': 0.5 + 0.5 * ((-1) ** (i // 2))}[contour]
            target = center - 2 + 5 * shape
            if resolve is not None:              # the note after an appoggiatura resolves it by step
                d, resolve = resolve, None
            elif part == 'B' and i == n - 1:    # the cadence: root or third of the last chord
                cands = [cd + 7 * o for o in range(-2, 4)] + [cd + 2 + 7 * o for o in range(-2, 4)]
                d = min(cands, key=lambda c: abs(c - prev) + 0.3 * abs(c - center))
            elif st % 8 == 0 or i == 0:          # strong beat: a chord tone near the line
                cands = [t + 7 * o for t in tones for o in range(-2, 4)]
                d = min(cands, key=lambda c: abs(c - prev) * 0.7 + abs(c - target) * 0.5 + rnd.random() * 0.8)
                nxt = slots[i + 1][0] if i + 1 < n else None
                if (i > 0 and nxt is not None and nxt - st <= 4 and nxt // STEPS_PER_BAR == bar
                        and not (part == 'B' and i + 1 == n - 1) and rnd.random() < tension):
                    resolve = d                  # lean on the note above (sometimes below), resolve next
                    d = d + (1 if rnd.random() < 0.7 else -1)
            else:                                # weak: a step (sometimes a leap) toward the contour
                direction = 1 if target > prev else -1
                r = rnd.random()
                mv = direction * (1 if r < 0.6 else 2) if r < 0.85 else -direction * rnd.choice([1, 3])
                d = prev + mv
            line.append(d)
            prev = d
        for (st, ln), dg in zip(slots, line):
            notes.append((st, ln, dg))
        if part == 'A':
            motif = ([line[i + 1] - line[i] for i in range(len(line) - 1)], 0)
    # last note held to the end of the phrase
    if notes:
        st, ln, dg = notes[-1]
        notes[-1] = (st, max(ln, bars * STEPS_PER_BAR - st), dg)
    return notes


def score(notes, key, chord_at, center, bars=None):
    """Higher is better. -> (score, details)

    What it rewards: chord tones on strong beats (or a non-chord note that resolves by step: an appoggiatura, which
    gives a line its pull), mostly stepwise motion with recovered leaps, a sensible range, one late high point, an open
    half-way point (question) and a closed ending (answer), some syncopation, enough different notes - and it
    penalises lines that only spell out the chords, which sound like arpeggios rather than tunes."""
    if len(notes) < 3:
        return -99, {}
    degs = [d for _, _, d in notes]
    ivs = [b - a for a, b in zip(degs, degs[1:])]

    def is_ct(st, d):
        return d % 7 in chord_degrees(chord_at(st // STEPS_PER_BAR))
    strong = [(i, st, d) for i, (st, _, d) in enumerate(notes) if st % 8 == 0]
    ct = app = bad = 0
    for i, st, d in strong:
        if is_ct(st, d):
            ct += 1
        elif i + 1 < len(notes) and abs(notes[i + 1][2] - d) == 1 and is_ct(notes[i + 1][0], notes[i + 1][2]):
            app += 1
        else:
            bad += 1
    ns = max(1, len(strong))
    ct_eff = (ct + app) / ns
    app_share = app / ns
    all_ct = sum(1 for st, _, d in notes if is_ct(st, d)) / len(notes)
    steps = sum(1 for i in ivs if abs(i) <= 1) / max(1, len(ivs))
    leaps = [i for i, v in enumerate(ivs) if abs(v) >= 3]
    recovered = sum(1 for i in leaps if i + 1 < len(ivs) and ivs[i + 1] * ivs[i] < 0) / max(1, len(leaps))
    rng = max(degs) - min(degs)
    hi_i = max(range(len(degs)), key=lambda i: (degs[i], i))
    climax = hi_i / (len(degs) - 1)
    end = degs[-1] % 7
    last_chord = chord_at(notes[-1][0] // STEPS_PER_BAR)
    ending = 1.0 if end == last_chord % 7 else 0.7 if end == (last_chord + 2) % 7 else 0.0
    runs = 0
    r = 1
    for i in ivs:
        r = r + 1 if i == 0 else 1
        runs += r >= 3
    peak_count = degs.count(max(degs))
    span_steps = bars * STEPS_PER_BAR if bars else max(st + ln for st, ln, _ in notes)
    half = span_steps // 2
    before = [d for st, _, d in notes if st < half]
    question = 1.0 if before and before[-1] % 7 != 0 else 0.0
    sync = sum(1 for st, _, _ in notes if st % 4 != 0) / len(notes)
    variety = len({d % 7 for d in degs})
    s = (3.0 * ct_eff - 1.0 * bad / ns + (0.8 if 0.08 <= app_share <= 0.34 else 0.0)
         + 2.0 * (1 - abs(steps - 0.65)) + 1.0 * recovered
         + (1.0 if 4 <= rng <= 9 else 0.3 if rng <= 11 else -1.0)
         + (1.2 if 0.5 <= climax <= 0.85 else 0.0) + (0.5 if peak_count <= 2 else 0)
         + 1.5 * ending + 0.8 * question
         + max(0.0, 1.0 - abs(sync - 0.35) * 2.5)
         + (0.5 if variety >= 4 else -1.0 if variety <= 2 else 0.0)
         - (1.5 * (all_ct - 0.8) / 0.2 if all_ct > 0.8 else 0.0)
         - 0.6 * runs - 0.05 * abs(sum(degs) / len(degs) - center))
    return s, dict(chord_tones=round(ct / ns, 2), tension=round(app_share, 2), steps=round(steps, 2), range=rng,
                   climax=round(climax, 2), ending=ending, question=question, syncopation=round(sync, 2))


def write_hook(key: Key, chord_at, bars, rhythms, density, center, rnd, candidates=48, tension=0.18):
    """-> (notes [(step, len_steps, degree)], info)"""
    best = None
    scores = []
    for _ in range(candidates):
        cells = _cells(rhythms, density, rnd)
        n = _candidate(key, chord_at, bars, cells, center, rnd, tension)
        s, det = score(n, key, chord_at, center, bars)
        scores.append(s)
        if best is None or s > best[0]:
            best = (s, n, det)
    s, n, det = best
    ok = sorted(x for x in scores if x > -50)
    median = ok[len(ok) // 2] if ok else s
    return n, dict(score=round(s, 2), median=round(median, 2), candidates=candidates, **det)


# ------------------------------------------------------------------ other lead devices
CHOP_RHYTHMS = ['..x..x....x.x...', '...x..x...x..x..', '.x..x...x..x..x.', '..x...x.x...x.x.', 'x..x..x...x.....']
OSTINATO_RHYTHMS = ['x.xx.xx.x.xx.xx.', 'x..x..x.x..x..x.', 'xx.x.xx.xx.x.xx.', 'x.x.x.x.x.x.x.x.']


def write_chops(key, chord_at, bars, center, rnd):
    """House / garage 'vocal chop' stabs: short syncopated hits on two or three high chord tones.
    The figure repeats; the last two bars of the phrase answer it with a variation."""
    rh = rnd.choice(CHOP_RHYTHMS)
    on = _onsets(rh)
    order = rnd.choice([[0, 1, 0, 2], [2, 1, 0, 1], [0, 0, 1, 2], [1, 2, 1, 0]])
    notes = []
    for bar in range(bars):
        cd = chord_at(bar)
        tones = sorted({t + 7 * o for t in chord_degrees(cd) for o in range(-1, 3)}, key=lambda d: abs(d - (center + 3)))[:3]
        tones.sort()
        answer = bars >= 4 and bar >= bars - 2
        steps = on if not answer else [s for s in on if s < 10] + ([12, 14] if rnd.random() < 0.6 else [12])
        for j, st in enumerate(steps):
            d = tones[order[(j + bar) % len(order)] % len(tones)]
            if answer and j == len(steps) - 1:
                d = tones[-1]
            notes.append((bar * STEPS_PER_BAR + st, 1 if rnd.random() < 0.7 else 2, d))
    return notes, dict(device='chops', notes=len(notes))


def write_ostinato(key, chord_at, bars, center, rnd):
    """Techno / acid sequence: a hypnotic 3-4 note figure that barely changes; one note moves every 4 bars."""
    rh = rnd.choice(OSTINATO_RHYTHMS)
    on = _onsets(rh)
    base = center - 2
    cell = [0, rnd.choice([2, 4]), rnd.choice([4, 7]), rnd.choice([-1, 2, 3])][:rnd.choice([3, 4])]
    notes = []
    for bar in range(bars):
        root = chord_at(bar)
        shifted = list(cell)
        if bar % 4 == 3:
            k = rnd.randrange(len(shifted))
            shifted[k] += rnd.choice([-1, 1, 2])
        for j, st in enumerate(on):
            notes.append((bar * STEPS_PER_BAR + st, 1, base + root % 7 + shifted[j % len(shifted)]))
    return notes, dict(device='ostinato', notes=len(notes))


def refit(line, chord_at_bar, tone_pcs_at_bar, key):
    """Fit a line to the chords that actually sound under it.
    Strong-beat notes become chord tones (unless they lean on one and resolve by step); held notes a semitone from
    a chord note move to the nearest chord tone. line: [(step, len, degree)]; chord_at_bar(bar) -> degree;
    tone_pcs_at_bar(bar) -> pitch classes sounding."""
    out = []
    for i, (st, ln, d) in enumerate(line):
        bar = st // STEPS_PER_BAR
        cd = chord_at_bar(bar)
        tones = chord_degrees(cd)
        near = lambda x: min((t + 7 * o for t in tones for o in range(-3, 5)), key=lambda c: (abs(c - x), c))  # noqa: E731
        if st % 8 == 0 and d % 7 not in tones:
            nxt = line[i + 1] if i + 1 < len(line) else None
            leaning = nxt and abs(nxt[2] - d) == 1 and nxt[0] // STEPS_PER_BAR == bar and nxt[2] % 7 in tones
            if not leaning:
                d = near(d)
        elif ln >= 4 and d % 7 not in tones:
            pcs = tone_pcs_at_bar(bar)
            pc = key.pc(d)
            if pcs and any((pc - c) % 12 in (1, 11) for c in pcs):
                d = near(d)
        out.append((st, ln, d))
    return out


def answer_phrase(lead, bars, chord_at_bar, rnd, register=-7):
    """Call and response: in each 2-bar half-phrase where the lead leaves a gap at the end, a second sound answers
    with the start of the lead's own figure, an octave (or a sixth) away. -> [(step, len, degree)]"""
    out = []
    seg = 2 * STEPS_PER_BAR
    for j in range(max(1, bars // 2)):
        a, b = j * seg, (j + 1) * seg
        inside = [n for n in lead if a <= n[0] < b]
        if not inside:
            continue
        last = max(st for st, _, _ in inside)       # lead notes are held legato, so measure from the last onset
        end = last + 3
        gap = b - end
        if gap < 5:
            continue
        figure = inside[:3]
        start = end + (1 if gap > 8 else 0)
        step = max(1, min(2, (b - start) // max(1, len(figure))))
        reg = register if rnd.random() < 0.7 else register + 2
        for k, (_, _, d) in enumerate(figure):
            st = start + k * step
            if st >= b:
                break
            out.append((st, step if k < len(figure) - 1 else max(step, b - st), d + reg))
    return out



def verse_variant(notes, chord_at, rnd):
    """Lower and thinner: drop some weak notes, move down a third, re-fit strong beats to the chords."""
    out = []
    for st, ln, d in notes:
        if st % 4 != 0 and rnd.random() < 0.35:
            continue
        d2 = d - 2
        if st % 8 == 0:
            tones = chord_degrees(chord_at(st // STEPS_PER_BAR))
            d2 = min((t + 7 * o for t in tones for o in range(-2, 4)), key=lambda x: abs(x - d2))
        out.append((st, ln, d2))
    # stretch lengths over removed notes
    fixed = []
    for i, (st, ln, d) in enumerate(out):
        nxt = out[i + 1][0] if i + 1 < len(out) else st + ln
        fixed.append((st, max(ln, min(nxt - st, 8)), d))
    return fixed


def skeleton(notes):
    """The hook's bones for a breakdown: only strong-beat notes, each held to the next."""
    strong = [(st, d) for st, _, d in notes if st % 8 == 0]
    if not strong:
        return notes
    end = max(st + ln for st, ln, _ in notes)
    return [(st, (strong[i + 1][0] if i + 1 < len(strong) else end) - st, d) for i, (st, d) in enumerate(strong)]


def fit_to_locked(prog_cands, locked_notes, key, bpc, loop_bars):
    """Pick the chord loop that best supports a locked melody: share of its strong-beat notes that are chord tones.
    locked_notes: [(beat, len, midi)] -> best progression."""
    def fit(prog):
        hit = tot = 0
        for beat, _, midi in locked_notes:
            if abs(beat - round(beat)) > 0.01 or int(round(beat)) % 2:
                continue
            bar = int(beat // 4)
            deg = prog[(bar // bpc) % len(prog)]
            d = key.degree_of(int(midi))
            tot += 1
            if d is not None and d % 7 in chord_degrees(deg):
                hit += 1
        return hit / max(1, tot)
    return max(prog_cands, key=fit), fit
