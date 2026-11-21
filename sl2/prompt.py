"""Describe a track in words -> settings, with a plain list of what was understood.

    "dark rolling liquid dnb in F minor, long, 174 bpm"  ->  genre liquid_dnb, key F minor, bpm 174, length long, energy ...
No AI service: keyword and pattern matching against every genre pack's keywords, plus mood words.
"""
import re

from . import genres as G
from .theory import parse_key

MOODS = {
    'dark': dict(energy=+0.0, brightness=-0.3, scales=['phrygian', 'minor']),
    'moody': dict(brightness=-0.2, scales=['minor', 'dorian']),
    'sad': dict(energy=-0.1, scales=['minor']),
    'melancholic': dict(energy=-0.1, scales=['minor', 'dorian']),
    'happy': dict(energy=+0.05, brightness=+0.2, scales=['major']),
    'uplifting': dict(energy=+0.1, brightness=+0.2, scales=['major', 'minor']),
    'euphoric': dict(energy=+0.15, brightness=+0.2),
    'sunny': dict(brightness=+0.2, scales=['major']),
    'summer': dict(brightness=+0.15, scales=['major', 'dorian']),
    'chill': dict(energy=-0.2),
    'relaxed': dict(energy=-0.25),
    'calm': dict(energy=-0.3),
    'mellow': dict(energy=-0.2),
    'hard': dict(energy=+0.2),
    'heavy': dict(energy=+0.2),
    'aggressive': dict(energy=+0.25, scales=['phrygian', 'minor']),
    'energetic': dict(energy=+0.2),
    'driving': dict(energy=+0.15),
    'minimal': dict(energy=-0.1),
    'dreamy': dict(energy=-0.1, brightness=-0.1, scales=['major', 'lydian', 'dorian']),
    'jazzy': dict(scales=['dorian']),
    'spooky': dict(scales=['harmonic_minor', 'phrygian']),
    'epic': dict(energy=+0.15),
}
LENGTH_WORDS = {'short': 'short', 'quick': 'short', 'radio': 'short', 'long': 'long', 'extended': 'long', 'club': 'long', 'dj': 'long'}


def parse(text):
    t = ' ' + text.lower().strip() + ' '
    out, said = {}, []
    # genre: the longest keyword match wins
    best = None
    for gid, g in G.all_genres().items():
        for kw in g.get('keywords', []) + [g['name'].lower(), gid.replace('_', ' ')]:
            if re.search(r'(?<![a-z])' + re.escape(kw.lower()) + r'(?![a-z])', t):
                if best is None or len(kw) > len(best[1]):
                    best = (gid, kw)
    if best:
        out['genre'] = best[0]
        said.append(f'genre: {G.load(best[0])["name"]} (from "{best[1]}")')
    m = re.search(r'(\d{2,3}(?:\.\d)?)\s*(?:bpm|beats)', t)
    if m:
        out['bpm'] = float(m.group(1))
        said.append(f'tempo: {out["bpm"]:g} BPM')
    m = re.search(r'\b(?:in|key of|key)\s+([a-g][#b♭]?\s*(?:m|min|minor|maj|major|dorian|phrygian|mixolydian|lydian|harmonic minor)?)(?![a-z])', t)
    if m:
        k = m.group(1).strip().replace('harmonic minor', 'harmonic_minor')
        k = k[0].upper() + k[1:]
        if parse_key(k):
            out['key'] = k
            said.append(f'key: {k}')
    energy = 0.6
    bright = 0.0
    scales = []
    for w, eff in MOODS.items():
        if re.search(r'(?<![a-z])' + w + r'(?![a-z])', t):
            energy += eff.get('energy', 0)
            bright += eff.get('brightness', 0)
            scales += eff.get('scales', [])
            said.append(f'mood: {w}')
    if energy != 0.6:
        out['energy'] = round(max(0.2, min(1.0, energy)), 2)
    if bright:
        out['brightness'] = round(max(-0.6, min(0.6, bright)), 2)
    if scales and 'key' not in out:
        out['scale_hint'] = scales[0]
    for w, L in LENGTH_WORDS.items():
        if re.search(r'(?<![a-z])' + w + r'(?![a-z])', t):
            out['length'] = L
            said.append(f'length: {L}')
            break
    m = re.search(r'(?:called|titled|named)\s+"?([^",.]+)"?', text, re.I)
    if m:
        out['title'] = m.group(1).strip().title()
        said.append(f'title: {out["title"]}')
    if not said:
        said.append("I didn't recognise a genre or setting - try words like 'deep dubstep', 'liquid dnb', '124 bpm', 'in F minor', 'dark', 'long'")
    return out, said
