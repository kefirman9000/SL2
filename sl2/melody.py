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


def _candidate(key, chord_at, bars, cells, center, rnd):
    """One melody: list of (step, len, degree)."""
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
        for i, (st, ln) in enumerate(slots):
            bar = st // STEPS_PER_BAR
            cd = chord_at(bar)
            tones = chord_degrees(cd)
            x = i / max(1, n - 1)
            shape = {'arch': 1 - abs(2 * x - 1), 'rise': x, 'fall': 1 - x, 'wave': 0.5 + 0.5 * ((-1) ** (i // 2))}[contour]
            target = center - 2 + 5 * shape
            if part == 'B' and i == n - 1:      # the cadence: root or third of the last chord
                cands = [cd + 7 * o for o in range(-2, 4)] + [cd + 2 + 7 * o for o in range(-2, 4)]
                d = min(cands, key=lambda c: abs(c - prev) + 0.3 * abs(c - center))
            elif st % 8 == 0 or i == 0:          # strong beat: a chord tone near the line
                cands = [t + 7 * o for t in tones for o in range(-2, 4)]
                d = min(cands, key=lambda c: abs(c - prev) * 0.7 + abs(c - target) * 0.5 + rnd.random() * 0.8)
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


def score(notes, key, chord_at, center):
    """Higher is better. -> (score, details)"""
    if len(notes) < 3:
        return -99, {}
    degs = [d for _, _, d in notes]
    ivs = [b - a for a, b in zip(degs, degs[1:])]
    strong = [(st, d) for st, _, d in notes if st % 8 == 0]
    ct = sum(1 for st, d in strong if d % 7 in chord_degrees(chord_at(st // STEPS_PER_BAR))) / max(1, len(strong))
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
    s = (3.0 * ct + 2.0 * (1 - abs(steps - 0.65)) + 1.0 * recovered
         + (1.0 if 4 <= rng <= 9 else 0.3 if rng <= 11 else -1.0)
         + (1.2 if 0.5 <= climax <= 0.85 else 0.0) + (0.5 if peak_count <= 2 else 0)
         + 1.5 * ending - 0.6 * runs - 0.05 * abs(sum(degs) / len(degs) - center))
    return s, dict(chord_tones=round(ct, 2), steps=round(steps, 2), range=rng, climax=round(climax, 2), ending=ending)


def write_hook(key: Key, chord_at, bars, rhythms, density, center, rnd, candidates=48):
    """-> (notes [(step, len_steps, degree)], info)"""
    best = None
    for _ in range(candidates):
        cells = _cells(rhythms, density, rnd)
        n = _candidate(key, chord_at, bars, cells, center, rnd)
        s, det = score(n, key, chord_at, center)
        if best is None or s > best[0]:
            best = (s, n, det)
    s, n, det = best
    return n, dict(score=round(s, 2), candidates=candidates, **det)


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
