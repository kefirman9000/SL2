"""Part effects: a chain of pedals on one part's stereo stem, the way inserts sit on a mixer channel.

A track's chain is `params['fx'] = [[name, {param: value}], ...]`, run in order after the notes are summed and before
the filter sweeps, auto-gain, sidechain and sends. Every effect is vectorised numpy / scipy (no per-sample Python loops),
and everything tempo-related is locked to the song's beat.

    drive     saturation: warm tape-ish (tanh), buzzy wavefolder, or hard clip - oversampled, no aliasing fizz
    crush     bit-crusher + sample-rate reducer (lo-fi, jungle, grime)
    chorus    two modulated delays, opposite phase left and right (Juno-style width and shimmer)
    phaser    four swept all-pass stages (the 90s house organ / Rhodes swirl)
    flanger   a short swept comb (jet-plane sweeps on hats, pads, breakdowns)
    gate      trance gate: a 16-step on/off pattern chopping a pad or chord in time
    pump      'LFO tool' volume shaper: a duck on every beat (sidechain feel without a kick)
    autopan   left-right sweep locked to the beat
    ott       3-band upward + downward compression (the dubstep / DnB 'everything loud' squash)
    comp      a compressor: threshold, ratio, attack, release, automatic make-up
    eq        low shelf, a mid bell and a high shelf
    filter    a fixed resonant low-, high- or band-pass (telephone vocals, dark techno stabs)
    echo      tempo-synced ping-pong echo with feedback, each repeat darker (dub techno throws)
    ring      ring modulator (metallic, inharmonic edges for bass-music FX and stabs)
    tape      wow, flutter, saturation and a soft top end (lo-fi, chill)
    stutter   beat-repeat: the last beat of each section turns into 1/16 or 1/32 repeats (build tension, DJ edits)
    reverse   reverse swells: each section's first beat, played backwards into the section (trance, dubstep intros)
"""
import numpy as np
from scipy import signal
from scipy.ndimage import maximum_filter1d, uniform_filter1d

SR = 44100

# name -> (label, default params, light / medium / heavy amounts)
EFFECTS = {
    'drive':   ('Drive', dict(amt=0.4, kind='tanh', mix=1.0), dict(light=dict(amt=0.2), medium=dict(amt=0.45), heavy=dict(amt=0.8))),
    'crush':   ('Bit-crusher', dict(bits=8, down=3, mix=0.6), dict(light=dict(bits=10, down=2, mix=0.4), medium=dict(bits=8, down=3, mix=0.6),
                                                                    heavy=dict(bits=5, down=6, mix=0.85))),
    'chorus':  ('Chorus', dict(depth=0.004, rate=0.6, mix=0.45), dict(light=dict(mix=0.3), medium=dict(mix=0.45), heavy=dict(mix=0.7, depth=0.007))),
    'phaser':  ('Phaser', dict(beats=4.0, depth=0.8, mix=0.5), dict(light=dict(mix=0.3), medium=dict(mix=0.5), heavy=dict(mix=0.75, beats=2.0))),
    'flanger': ('Flanger', dict(beats=8.0, depth=0.0025, mix=0.5), dict(light=dict(mix=0.3), medium=dict(mix=0.5), heavy=dict(mix=0.7, beats=4.0))),
    'gate':    ('Trance gate', dict(pattern='x.xxx.xx.x.xx.xx', depth=0.85, smooth=0.004),
                dict(light=dict(depth=0.5), medium=dict(depth=0.85), heavy=dict(depth=1.0, pattern='x.x.x.x.x.x.x.x.'))),
    'pump':    ('Pump (LFO tool)', dict(beats=1.0, depth=0.6, curve=2.5), dict(light=dict(depth=0.35), medium=dict(depth=0.6), heavy=dict(depth=0.9))),
    'autopan': ('Auto-pan', dict(beats=2.0, depth=0.6), dict(light=dict(depth=0.3), medium=dict(depth=0.6), heavy=dict(depth=1.0, beats=1.0))),
    'ott':     ('OTT (multiband squash)', dict(amt=0.5, mix=1.0), dict(light=dict(amt=0.25), medium=dict(amt=0.5), heavy=dict(amt=0.85))),
    'comp':    ('Compressor', dict(threshold=-18.0, ratio=4.0, attack=0.005, release=0.12),
                dict(light=dict(threshold=-12.0, ratio=2.0), medium=dict(threshold=-18.0, ratio=4.0), heavy=dict(threshold=-26.0, ratio=8.0, attack=0.001))),
    'eq':      ('EQ', dict(low=0.0, mid=0.0, mid_hz=1200.0, high=0.0),
                dict(light=dict(high=2.0), medium=dict(low=2.0, high=3.0), heavy=dict(low=4.0, mid=-3.0, high=5.0))),
    'filter':  ('Filter', dict(kind='lp', cutoff=1800.0, res=0.3), dict(light=dict(cutoff=5000.0), medium=dict(cutoff=1800.0), heavy=dict(cutoff=700.0, res=0.6))),
    'echo':    ('Echo (synced)', dict(beats=0.75, fb=0.45, mix=0.3, tone=3000.0),
                dict(light=dict(mix=0.18, fb=0.3), medium=dict(mix=0.3, fb=0.45), heavy=dict(mix=0.45, fb=0.68))),
    'ring':    ('Ring mod', dict(freq=320.0, mix=0.35), dict(light=dict(mix=0.2), medium=dict(mix=0.35), heavy=dict(mix=0.6, freq=180.0))),
    'tape':    ('Tape', dict(wow=0.5, sat=0.4, tone=9000.0), dict(light=dict(wow=0.3, sat=0.2), medium=dict(wow=0.5, sat=0.4), heavy=dict(wow=1.0, sat=0.7, tone=6000.0))),
    'stutter': ('Stutter (beat repeat)', dict(beats=1.0, slice=0.25), dict(light=dict(beats=0.5, slice=0.25), medium=dict(beats=1.0, slice=0.25),
                                                                            heavy=dict(beats=2.0, slice=0.125))),
    'reverse': ('Reverse swell', dict(beats=1.0, mix=0.6), dict(light=dict(mix=0.35), medium=dict(mix=0.6), heavy=dict(mix=0.9, beats=2.0))),
}
STRINGS = {'kind', 'pattern'}


def clean_chain(chain):
    """Validate a chain from the outside world (the editor, a song file): known effects, numbers in range."""
    out = []
    for item in chain or []:
        if not isinstance(item, (list, tuple)) or not item or item[0] not in EFFECTS:
            continue
        name = item[0]
        given = item[1] if len(item) > 1 and isinstance(item[1], dict) else {}
        p = {}
        for k, v in given.items():
            if k not in EFFECTS[name][1]:
                continue
            if k in STRINGS:
                v = str(v)[:32]
                if k == 'kind' and v not in ('tanh', 'fold', 'hard', 'lp', 'hp', 'bp'):
                    continue
                if k == 'pattern' and not set(v) <= set('xX.o'):
                    continue
            else:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    continue
                if not np.isfinite(v):
                    continue
                v = float(np.clip(v, -48, 20000))
            p[k] = v
        out.append([name, p])
    return out[:8]


def preset(name, amount='medium'):
    label, d, amts = EFFECTS[name]
    return [name, dict(d, **amts.get(amount, {}))]


# ------------------------------------------------------------------ helpers
def _mix(dry, wet, mix):
    return dry * (1 - mix) + wet * mix


def _frac_delay(x, delay_samples):
    """x delayed by a per-sample (fractional) amount, by interpolation. x: (n,), delay: (n,)."""
    n = len(x)
    idx = np.arange(n) - delay_samples
    return np.interp(idx, np.arange(n), x, left=0.0)


def _beat_lfo(n, beat_s, beats, phase=0.0, shape='sine'):
    t = np.arange(n) / SR
    ph = (t / (beat_s * max(beats, 1e-3)) + phase) % 1.0
    if shape == 'tri':
        return 1 - np.abs(2 * ph - 1)
    return 0.5 - 0.5 * np.cos(2 * np.pi * ph)


def _sos(kind, fc, q=0.707, gain_db=0.0):
    fc = float(np.clip(fc, 20, SR * 0.45))
    w = 2 * np.pi * fc / SR
    c, s_ = np.cos(w), np.sin(w)
    al = s_ / (2 * q)
    A = 10 ** (gain_db / 40)
    if kind == 'lp':
        b, a = [(1 - c) / 2, 1 - c, (1 - c) / 2], [1 + al, -2 * c, 1 - al]
    elif kind == 'hp':
        b, a = [(1 + c) / 2, -(1 + c), (1 + c) / 2], [1 + al, -2 * c, 1 - al]
    elif kind == 'bp':
        b, a = [al, 0, -al], [1 + al, -2 * c, 1 - al]
    elif kind == 'peak':
        b, a = [1 + al * A, -2 * c, 1 - al * A], [1 + al / A, -2 * c, 1 - al / A]
    elif kind == 'lowshelf':
        sq = 2 * np.sqrt(A) * al
        b = [A * ((A + 1) - (A - 1) * c + sq), 2 * A * ((A - 1) - (A + 1) * c), A * ((A + 1) - (A - 1) * c - sq)]
        a = [(A + 1) + (A - 1) * c + sq, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - sq]
    else:  # highshelf
        sq = 2 * np.sqrt(A) * al
        b = [A * ((A + 1) + (A - 1) * c + sq), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sq)]
        a = [(A + 1) - (A - 1) * c + sq, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sq]
    b, a = np.array(b) / a[0], np.array(a) / a[0]
    return np.concatenate([b, a])[None, :]


# ------------------------------------------------------------------ the effects: f(x (2, n) float64, p, ctx) -> (2, n)
def drive(x, p, ctx):
    from .va_bass import dist
    amt = float(p['amt'])
    y = dist(x, 1.0 + amt * 7.0, p.get('kind', 'tanh'))
    y *= np.sqrt((x ** 2).mean() / max((y ** 2).mean(), 1e-12))          # roughly level-matched
    return _mix(x, y, float(p['mix']))


def crush(x, p, ctx):
    bits = max(2, int(p['bits']))
    down = max(1, int(p['down']))
    y = np.repeat(x[:, ::down], down, axis=1)[:, :x.shape[1]]
    q = 2 ** (bits - 1)
    y = np.round(y * q) / q
    return _mix(x, y, float(p['mix']))


def chorus(x, p, ctx):
    n = x.shape[1]
    t = np.arange(n) / SR
    out = np.empty_like(x)
    for ch, ph in ((0, 0.0), (1, np.pi)):
        d = (0.007 + float(p['depth']) * (0.5 + 0.5 * np.sin(2 * np.pi * float(p['rate']) * t + ph))) * SR
        out[ch] = _frac_delay(x[ch], d)
    return _mix(x, out, float(p['mix']) * 0.7) * (1 + 0.15 * float(p['mix']))


def phaser(x, p, ctx):
    n = x.shape[1]
    lfo = _beat_lfo(n, ctx['beat'], float(p['beats']))
    fc = 300 * (4000 / 300) ** (lfo * float(p['depth']))
    out = np.empty_like(x)
    block = 128
    for ch in range(2):
        y = x[ch].copy()
        for stage in range(4):
            z = np.zeros(1)
            res = np.empty(n)
            for s in range(0, n, block):
                w = np.tan(np.pi * fc[s] / SR)
                a1 = (w - 1) / (w + 1)
                res[s:s + block], z = signal.lfilter([a1, 1.0], [1.0, a1], y[s:s + block], zi=z)
            y = res
        out[ch] = y
    m = float(p['mix'])
    return (x + m * out) / (1 + m) * (1 + 0.4 * m)             # dry + swept all-pass = moving notches


def flanger(x, p, ctx):
    n = x.shape[1]
    lfo = _beat_lfo(n, ctx['beat'], float(p['beats']), shape='tri')
    out = np.empty_like(x)
    for ch, off in ((0, 0.0), (1, 0.25)):
        l2 = _beat_lfo(n, ctx['beat'], float(p['beats']), phase=off, shape='tri') if ch else lfo
        d = (0.0003 + float(p['depth']) * l2) * SR
        out[ch] = x[ch] + 0.7 * _frac_delay(x[ch], d)
    return _mix(x, out * 0.7, float(p['mix']))


def gate(x, p, ctx):
    n = x.shape[1]
    pat = p.get('pattern') or 'x.xxx.xx.x.xx.xx'
    step = ctx['beat'] / 4
    t = np.arange(n) / SR
    idx = (t / step).astype(int) % len(pat)
    on = np.array([1.0 if c in 'xX' else 0.55 if c == 'o' else 0.0 for c in pat])[idx]
    k = max(1, int(float(p['smooth']) * SR))
    on = uniform_filter1d(on, k)
    g = 1 - float(p['depth']) * (1 - on)
    return x * g


def pump(x, p, ctx):
    n = x.shape[1]
    t = np.arange(n) / SR
    ph = (t / (ctx['beat'] * float(p['beats']))) % 1.0
    g = 1 - float(p['depth']) * (1 - np.clip(ph * 3, 0, 1)) ** float(p['curve'])
    return x * uniform_filter1d(g, 64)


def autopan(x, p, ctx):
    n = x.shape[1]
    lfo = _beat_lfo(n, ctx['beat'], float(p['beats']))
    pan = (lfo - 0.5) * float(p['depth'])                                      # -0.5 .. 0.5
    a = (pan + 0.5) * np.pi / 2
    m = x.mean(0)
    side = (x[0] - x[1]) / 2
    return np.vstack([m * np.cos(a) * 1.414 + side, m * np.sin(a) * 1.414 - side])


def ott(x, p, ctx):
    amt = float(p['amt'])
    lo = signal.sosfilt(signal.butter(4, 120 / (SR / 2), 'low', output='sos'), x, axis=1)
    hi = signal.sosfilt(signal.butter(4, 2500 / (SR / 2), 'high', output='sos'), x, axis=1)
    mid = x - lo - hi
    out = np.zeros_like(x)
    for band, up in ((lo, 1.0), (mid, 1.0), (hi, 1.3)):
        env = np.sqrt(np.maximum(uniform_filter1d((band ** 2).mean(0), int(0.012 * SR)), 0.0)) + 1e-7
        sounding = env > 10 ** (-60 / 20) * max(env.max(), 1e-9) * 30
        if not sounding.any():
            out += band
            continue
        tgt = float(np.percentile(env[sounding], 85))
        g = np.clip((tgt / env) ** amt, 0.25, 1 + 5 * amt * up)
        g = np.where(sounding, g, 1.0)
        out += band * uniform_filter1d(g, 128)
    out *= np.sqrt((x ** 2).mean() / max((out ** 2).mean(), 1e-12))
    return _mix(x, out, float(p['mix']))


def comp(x, p, ctx):
    lvl = np.abs(x).max(0)
    att = max(1, int(float(p['attack']) * SR))
    rel = max(1, int(float(p['release']) * SR))
    env = maximum_filter1d(lvl, att)
    a = np.exp(-1 / rel)
    env = signal.lfilter([1 - a], [1, -a], env)
    env = np.maximum(env, lvl * 0)
    db = 20 * np.log10(env + 1e-9)
    over = np.maximum(0, db - float(p['threshold']))
    gr = over * (1 - 1 / max(1.0, float(p['ratio'])))
    y = x * 10 ** (-gr / 20)
    return y * np.sqrt((x ** 2).mean() / max((y ** 2).mean(), 1e-12))         # make-up gain


def eq(x, p, ctx):
    sos = []
    if abs(float(p['low'])) > 0.05:
        sos.append(_sos('lowshelf', 110, 0.7, float(p['low'])))
    if abs(float(p['mid'])) > 0.05:
        sos.append(_sos('peak', float(p['mid_hz']), 1.0, float(p['mid'])))
    if abs(float(p['high'])) > 0.05:
        sos.append(_sos('highshelf', 7500, 0.7, float(p['high'])))
    return signal.sosfilt(np.vstack(sos), x, axis=1) if sos else x


def filt(x, p, ctx):
    q = 0.707 + 6 * float(p['res']) ** 1.5
    return signal.sosfilt(_sos(p.get('kind', 'lp'), float(p['cutoff']), q), x, axis=1)


def echo(x, p, ctx):
    n = x.shape[1]
    d = int(float(p['beats']) * ctx['beat'] * SR)
    if d <= 0 or d >= n:
        return x
    wet = np.zeros_like(x)
    src = x.mean(0)
    sos = _sos('lp', float(p['tone']))
    g = 1.0
    e = src
    for k in range(1, 24):
        e = signal.sosfilt(sos, e) * (float(p['fb']) if k > 1 else 1.0)
        g = np.abs(e).max()
        sh = d * k
        if sh >= n or g < 1e-3:
            break
        wet[k % 2, sh:] += e[:n - sh]
    return x + wet * float(p['mix'])


def ring(x, p, ctx):
    t = np.arange(x.shape[1]) / SR
    return _mix(x, x * np.sin(2 * np.pi * float(p['freq']) * t), float(p['mix']))


def tape(x, p, ctx):
    n = x.shape[1]
    t = np.arange(n) / SR
    wow = float(p['wow'])
    d = (0.004 + 0.0012 * wow * np.sin(2 * np.pi * 0.55 * t) + 0.0002 * wow * np.sin(2 * np.pi * 7.3 * t)) * SR
    y = np.vstack([_frac_delay(x[0], d), _frac_delay(x[1], d)])
    s = float(p['sat'])
    if s > 0:
        k = 1 + 3 * s
        y = np.tanh(y * k) / np.tanh(k)
        y *= np.sqrt((x ** 2).mean() / max((y ** 2).mean(), 1e-12))
    return signal.sosfilt(_sos('lp', float(p['tone']), 0.6), y, axis=1)


def stutter(x, p, ctx):
    y = x.copy()
    n = x.shape[1]
    span = int(float(p['beats']) * ctx['beat'] * SR)
    sl = max(64, int(float(p['slice']) * ctx['beat'] * SR))
    for _, end in ctx.get('sections', [])[:-1]:
        e = int(end * SR)
        s = e - span
        if s <= 0 or e > n:
            continue
        piece = x[:, s:s + sl].copy()
        fade = min(64, sl // 4)
        piece[:, -fade:] *= np.linspace(1, 0, fade)
        reps = int(np.ceil(span / sl))
        y[:, s:e] = np.tile(piece, reps)[:, :e - s]
    return y


def reverse(x, p, ctx):
    y = x.copy()
    n = x.shape[1]
    span = int(float(p['beats']) * ctx['beat'] * SR)
    for start, _ in ctx.get('sections', [])[1:]:
        s = int(start * SR)
        if s - span < 0 or s + span > n:
            continue
        seg = x[:, s:s + span][:, ::-1]
        env = np.linspace(0, 1, span) ** 2
        y[:, s - span:s] += seg * env * float(p['mix'])
    return y


FUNCS = dict(drive=drive, crush=crush, chorus=chorus, phaser=phaser, flanger=flanger, gate=gate, pump=pump, autopan=autopan,
             ott=ott, comp=comp, eq=eq, filter=filt, echo=echo, ring=ring, tape=tape, stutter=stutter, reverse=reverse)


def apply_chain(buf, chain, beat_s, sections=None):
    """buf (2, n) float32 -> (2, n) float32 through every effect in `chain`."""
    if not chain:
        return buf
    x = buf.astype(np.float64)
    ctx = dict(beat=float(beat_s), sections=sections or [])
    for name, p in chain:
        fn = FUNCS.get(name)
        if fn is None:
            continue
        params = dict(EFFECTS[name][1], **(p or {}))
        x = fn(x, params, ctx)
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    return x.astype(np.float32)


def menu():
    """For the editor: every effect with its three ready-made amounts (full parameter sets)."""
    return [dict(id=k, label=v[0], presets={a: preset(k, a)[1] for a in ('light', 'medium', 'heavy')}) for k, v in EFFECTS.items()]
