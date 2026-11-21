"""Music theory: keys, scales, diatonic chords, voice leading, and seeded randomness."""
import random
import re

NOTE_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
_PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

SCALES = {
    'major': [0, 2, 4, 5, 7, 9, 11],
    'minor': [0, 2, 3, 5, 7, 8, 10],
    'dorian': [0, 2, 3, 5, 7, 9, 10],
    'phrygian': [0, 1, 3, 5, 7, 8, 10],
    'mixolydian': [0, 2, 4, 5, 7, 9, 10],
    'lydian': [0, 2, 4, 6, 7, 9, 11],
    'harmonic_minor': [0, 2, 3, 5, 7, 8, 11],
}
MINORISH = {'minor', 'dorian', 'phrygian', 'harmonic_minor'}
ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII']


def rng(seed, *parts):
    """A random generator for one decision, seeded by the song seed AND what it decides (genre, part ...).
    Two genres with the same seed never share a key, and re-rolling one part leaves the others alone."""
    return random.Random('|'.join(str(p) for p in (seed,) + parts))


def pc_of(name):
    name = name.strip()
    pc = _PC[name[0].upper()]
    for ch in name[1:]:
        pc += 1 if ch == '#' else -1 if ch in 'b♭' else 0
    return pc % 12


def parse_key(text):
    """'F minor', 'F#m', 'Am', 'Eb dorian', 'C' -> (root pc, scale) or None."""
    if not text:
        return None
    m = re.fullmatch(r'\s*([A-Ga-g])([#b♭]?)\s*(m|min|minor|maj|major|' + '|'.join(SCALES) + r')?\s*', text)
    if not m:
        return None
    root = pc_of(m.group(1) + m.group(2))
    q = (m.group(3) or 'major').lower()
    scale = {'m': 'minor', 'min': 'minor', 'maj': 'major'}.get(q, q)
    return root, scale


class Key:
    def __init__(self, root, scale='minor'):
        self.root = int(root) % 12
        self.scale_name = scale
        self.scale = SCALES[scale]

    def name(self):
        return f"{NOTE_NAMES[self.root]} {self.scale_name.replace('_', ' ')}"

    @property
    def minor(self):
        return self.scale_name in MINORISH

    def pc(self, degree):
        o, i = divmod(int(degree), 7)
        return (self.root + self.scale[i]) % 12

    def midi(self, degree, octave=4):
        o, i = divmod(int(degree), 7)
        return 12 * (octave + 1 + o) + self.root + self.scale[i]

    def in_key(self, pc):
        return (pc - self.root) % 12 in self.scale

    def degree_of(self, midi):
        """Scale degree (with octave) of a MIDI note, or None if it's outside the scale."""
        rel = (midi - self.root) % 12
        if rel not in self.scale:
            return None
        return self.scale.index(rel) + 7 * ((midi - self.root) // 12)

    def chord_pcs(self, degree, size=3):
        return [self.pc(degree + 2 * i) for i in range(size)]

    def quality(self, degree):
        a, b, c = (self.scale[(degree + k) % 7] + 12 * ((degree + k) // 7) for k in (0, 2, 4))
        third, fifth = (b - a) % 12, (c - a) % 12
        return {(4, 7): 'maj', (3, 7): 'min', (3, 6): 'dim', (4, 8): 'aug'}.get((third, fifth), '?')

    def roman(self, degree):
        r = ROMAN[degree % 7]
        q = self.quality(degree % 7)
        if q == 'maj':
            return r
        if q == 'min':
            return r.lower()
        if q == 'dim':
            return r.lower() + '°'
        return r + '+'

    def scale_midis(self, lo, hi):
        return [m for m in range(lo, hi + 1) if self.in_key(m % 12)]


def voicings(pcs, lo, hi):
    """Every close voicing (all inversions, every octave) of a chord that fits between lo and hi."""
    out = []
    n = len(pcs)
    for inv in range(n):
        order = pcs[inv:] + pcs[:inv]
        for base in range(lo, hi):
            if base % 12 != order[0]:
                continue
            v = [base]
            for p in order[1:]:
                nxt = v[-1] + ((p - v[-1]) % 12 or 12)
                v.append(nxt)
            if v[-1] <= hi:
                out.append(v)
    return out


def voice_lead(pcs, prev, lo=52, hi=79, center=None):
    """The voicing of a chord that moves least from the previous one (and stays near the middle of the range)."""
    cands = voicings(pcs, lo, hi)
    if not cands:
        return sorted(lo + ((p - lo) % 12) for p in pcs)
    center = center if center is not None else (lo + hi) / 2

    def cost(v):
        c = abs(sum(v) / len(v) - center) * 0.35
        if prev:
            a, b = sorted(prev), sorted(v)
            m = min(len(a), len(b))
            c += sum(abs(a[i] - b[i]) for i in range(m))
        return c
    return min(cands, key=cost)


def nearest(midi_choices, target):
    return min(midi_choices, key=lambda m: (abs(m - target), m))


def color_pcs(key, degree, size, add9):
    """A chord's pitch classes with its colour notes (7th, 9th), leaving out colours that don't sound like that chord:
    a 9th a semitone above the root (b9), or a 7th on a diminished triad. -> (pcs, core) where core is the triad."""
    core = key.chord_pcs(degree, 3)
    pcs = list(core)
    if size >= 4 and key.quality(degree % 7) != 'dim':
        pcs.append(key.pc(degree + 6))
    if add9:
        nine = key.pc(degree + 8)
        if (nine - core[0]) % 12 != 1:
            pcs.append(nine)
    return pcs, core


def declutter(voicing, core_pcs, hi):
    """No two notes a semitone apart: the colour note (7th / 9th) moves up an octave, where it rings open, or is
    dropped when that would leave the range."""
    v = sorted(voicing)
    for _ in range(6):
        clash = next(((a, b) for a, b in zip(v, v[1:]) if b - a == 1), None)
        if not clash:
            break
        a, b = clash
        mover = a if a % 12 not in core_pcs else b if b % 12 not in core_pcs else None
        if mover is None:
            break
        v.remove(mover)
        if mover + 12 <= hi + 5 and mover + 12 not in v:
            v.append(mover + 12)
        v.sort()
    return v
