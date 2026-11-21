"""Instruments: every sound SL2 plays, synthesized with numpy (no samples needed).

play(inst, freq, dur, vel, sr, p) -> float32 array (2, n): one note, stereo, including its release tail.
Drums ignore freq (except toms / 808s); fx use p['kind'].
"""
import functools
import math

import numpy as np
from scipy import signal

SR = 44100


# ------------------------------------------------------------------ building blocks
def _t(n, sr=SR):
    return np.arange(n, dtype=np.float64) / sr


def _poly_blep(ph, dt):
    dt = np.broadcast_to(dt, ph.shape)
    out = np.zeros_like(ph)
    m = ph < dt
    x = ph[m] / dt[m]
    out[m] = x + x - x * x - 1
    m2 = ph > 1 - dt
    x = (ph[m2] - 1) / dt[m2]
    out[m2] = x * x + x + x + 1
    return out


def saw(freq, n, sr=SR, phase=0.0, fm=None):
    """Band-limited saw. freq may be a scalar or a per-sample array (vibrato, glide)."""
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (n,))
    inc = f / sr
    ph = (phase + np.cumsum(inc) - inc[0]) % 1.0
    return (2 * ph - 1 - _poly_blep(ph, np.maximum(inc, 1e-6))).astype(np.float64)


def square(freq, n, sr=SR, pw=0.5, phase=0.0):
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (n,))
    inc = f / sr
    ph = (phase + np.cumsum(inc) - inc[0]) % 1.0
    dt = np.maximum(inc, 1e-6)
    s = np.where(ph < pw, 1.0, -1.0)
    s += _poly_blep(ph, dt)
    s -= _poly_blep((ph - pw) % 1.0, dt)
    return s


def sine(freq, n, sr=SR, phase=0.0):
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (n,))
    ph = 2 * np.pi * (np.cumsum(f) / sr) + phase
    return np.sin(ph)


def noise(n, seed=0):
    return np.random.default_rng(seed).standard_normal(n)


def adsr(n, a, d, s, r, dur_n, sr=SR):
    """Attack / decay / sustain level / release envelope. dur_n = samples until note-off; n = total samples."""
    a_n, d_n, r_n = max(1, int(a * sr)), max(1, int(d * sr)), max(1, int(r * sr))
    env = np.empty(n)
    i = np.arange(n)
    env[:] = s
    env[i < a_n] = i[i < a_n] / a_n
    m = (i >= a_n) & (i < a_n + d_n)
    env[m] = 1 - (1 - s) * (i[m] - a_n) / d_n
    off = min(dur_n, n)
    lvl = env[off - 1] if off > 0 else 0
    m = i >= off
    env[m] = lvl * np.maximum(0, 1 - (i[m] - off) / r_n)
    return env


def expdecay(n, t60, sr=SR):
    return np.exp(-6.9 * _t(n, sr) / max(t60, 1e-3))


def lp(x, fc, sr=SR, order=2):
    fc = min(max(fc, 20), sr * 0.45)
    return signal.sosfilt(signal.butter(order, fc / (sr / 2), 'low', output='sos'), x)


def hp(x, fc, sr=SR, order=2):
    fc = min(max(fc, 10), sr * 0.45)
    return signal.sosfilt(signal.butter(order, fc / (sr / 2), 'high', output='sos'), x)


def bp(x, lo, hi, sr=SR, order=2):
    return signal.sosfilt(signal.butter(order, [max(lo, 20) / (sr / 2), min(hi, sr * 0.45) / (sr / 2)], 'band', output='sos'), x)


def res_lp_sweep(x, cutoff, q=4.0, sr=SR, block=64):
    """Resonant low-pass whose cutoff moves over time (cutoff: per-sample array). RBJ biquad, updated per block."""
    y = np.empty_like(x)
    zi = np.zeros(2)
    for i in range(0, len(x), block):
        fc = float(np.clip(cutoff[min(i, len(cutoff) - 1)], 30, sr * 0.45))
        w = 2 * np.pi * fc / sr
        al = np.sin(w) / (2 * q)
        c = np.cos(w)
        b = np.array([(1 - c) / 2, 1 - c, (1 - c) / 2])
        a = np.array([1 + al, -2 * c, 1 - al])
        y[i:i + block], zi = signal.lfilter(b / a[0], a / a[0], x[i:i + block], zi=zi)
    return y


def sweep(x, cutoff, kind='lp', q=0.707, sr=SR, block=128):
    """Low- or high-pass whose cutoff moves over time (cutoff: per-sample array). RBJ biquad, updated per block."""
    y = np.empty_like(x)
    zi = np.zeros(2)
    for i in range(0, len(x), block):
        fc = float(np.clip(cutoff[min(i, len(cutoff) - 1)], 20, sr * 0.45))
        w = 2 * np.pi * fc / sr
        al = np.sin(w) / (2 * q)
        c = np.cos(w)
        if kind == 'hp':
            b = np.array([(1 + c) / 2, -(1 + c), (1 + c) / 2])
        else:
            b = np.array([(1 - c) / 2, 1 - c, (1 - c) / 2])
        a = np.array([1 + al, -2 * c, 1 - al])
        y[i:i + block], zi = signal.lfilter(b / a[0], a / a[0], x[i:i + block], zi=zi)
    return y


def soft(x, drive=1.0):
    return np.tanh(x * drive) / np.tanh(drive)


def stereo(m, width=0.0, seed=0):
    """Mono -> stereo; width adds a short decorrelating delay on one side (Haas)."""
    if width <= 0:
        return np.vstack([m, m])
    d = int(0.004 * width * SR) + 1
    r = np.concatenate([np.zeros(d), m[:-d]])
    return np.vstack([m * (1 - 0.15 * width), r * (1 - 0.15 * width) + m * 0.15 * width])


def detuned_stack(osc, freq, n, voices=7, spread=0.25, seed=1):
    """Supersaw-style stack: voices spread over +-spread semitones, panned alternately. -> (2, n)"""
    rng = np.random.default_rng(seed)
    L = np.zeros(n)
    R = np.zeros(n)
    for v in range(voices):
        off = (v - (voices - 1) / 2) / max(1, (voices - 1) / 2) * spread
        f = freq * 2 ** (off / 12)
        s = osc(f, n, phase=rng.random())
        pan = 0.5 + 0.45 * ((v % 2) * 2 - 1) * (abs(off) / spread if spread else 0)
        L += s * math.cos(pan * math.pi / 2)
        R += s * math.sin(pan * math.pi / 2)
    return np.vstack([L, R]) / math.sqrt(voices)


# ------------------------------------------------------------------ melodic instruments
def _len(dur, rel):
    return int((dur + rel) * SR) + 1


def i_sub(f, dur, vel, p):
    n = _len(dur, 0.06)
    x = sine(f, n) + 0.12 * sine(2 * f, n)
    x = soft(x * 1.3, 1.3)
    return stereo(x * adsr(n, 0.004, 0.1, 0.9, 0.05, int(dur * SR)))


def i_organ_bass(f, dur, vel, p):
    """House organ bass (M1-style): sub sine + a bright, quickly decaying organ body."""
    n = _len(dur, 0.05)
    body = sine(f, n) + 0.5 * sine(2 * f, n) + 0.3 * sine(3 * f, n) + 0.15 * sine(4 * f, n)
    env_b = expdecay(n, 0.35)
    x = 0.8 * sine(f, n) + 0.55 * body * env_b
    return stereo(soft(x, 1.2) * adsr(n, 0.003, 0.05, 0.85, 0.04, int(dur * SR)))


def i_bass_pluck(f, dur, vel, p):
    n = _len(dur, 0.05)
    raw = saw(f, n) * 0.6 + square(f, n, pw=0.3) * 0.4
    bright = lp(raw, 2500)
    dark = lp(raw, 300)
    e = expdecay(n, 0.12)
    x = bright * e + dark * (1 - e) + 0.6 * sine(f, n)
    return stereo(soft(x, 1.5) * adsr(n, 0.002, 0.15, 0.6, 0.04, int(dur * SR)))


def i_bass_synth(f, dur, vel, p):
    """Driving analog saw bass (synthwave, trance, melodic techno)."""
    n = _len(dur, 0.05)
    raw = saw(f, n) + 0.5 * saw(f * 1.004, n, phase=0.3)
    e = expdecay(n, 0.18)
    cut = 250 + 2200 * e * (0.5 + 0.5 * vel)
    x = res_lp_sweep(raw, cut, q=1.2) + 0.7 * sine(f, n)
    return stereo(soft(x * 0.8, 1.4) * adsr(n, 0.003, 0.1, 0.8, 0.04, int(dur * SR)))


def i_bass_fm(f, dur, vel, p):
    """UK garage FM bass: punchy, a little growly."""
    n = _len(dur, 0.05)
    t = _t(n)
    idx = 2.5 * expdecay(n, 0.2) + 0.6
    x = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * t))
    x = soft(x + 0.6 * sine(f, n), 1.6)
    return stereo(x * adsr(n, 0.002, 0.1, 0.8, 0.04, int(dur * SR)))


def i_reese(f, dur, vel, p):
    n = _len(dur, 0.08)
    a = saw(f * 2 ** (-0.12 / 12), n, phase=0.1)
    b = saw(f * 2 ** (0.12 / 12), n, phase=0.6)
    body = lp((a + b) * 0.5, 650, order=4)
    mid = bp((a - b) * 0.5, 400, 1400)
    sub = sine(f, n)
    x = soft(0.9 * sub + 0.8 * body, 1.8)
    out = np.vstack([x + 0.35 * mid, x - 0.35 * mid])
    return out * adsr(n, 0.01, 0.1, 0.9, 0.06, int(dur * SR))


def i_wobble(f, dur, vel, p):
    """Dubstep wobble: saw + square through a resonant filter swept by a tempo-synced LFO (p['rate'] Hz)."""
    n = _len(dur, 0.05)
    rate = float(p.get('rate', 4.0))
    t = _t(n)
    raw = saw(f, n) + 0.7 * square(f * 0.5, n, pw=0.4) + 0.5 * saw(f * 1.01, n, phase=0.4)
    lfo = 0.5 - 0.5 * np.cos(2 * np.pi * rate * t)
    cut = 120 + 2400 * lfo ** 1.6
    x = res_lp_sweep(raw, cut, q=3.0)
    x = soft(x * 0.9, 2.2) + 0.8 * sine(f, n)
    return stereo(x * adsr(n, 0.005, 0.05, 0.95, 0.05, int(dur * SR)), 0.3)


def i_808(f, dur, vel, p):
    """Trap 808: sine with a pitch dip, long decay, saturated; glides from p['from'] if given."""
    n = _len(dur, 0.12)
    t = _t(n)
    start = float(p.get('from', f))
    glide = np.where(t < 0.09, start + (f - start) * (t / 0.09), f)
    pitch = glide * (1 + 0.6 * np.exp(-t / 0.03))
    x = sine(pitch, n)
    env = adsr(n, 0.002, 0.05, 0.9, 0.1, int(dur * SR)) * np.exp(-t / max(1.2, dur))
    return stereo(soft(x * 1.6, 2.0) * env)


def i_acid(f, dur, vel, p):
    """303-style: saw through a squelchy resonant sweep; p['accent'] opens it further."""
    n = _len(dur, 0.04)
    acc = float(p.get('accent', 0.0))
    raw = saw(f, n) if not p.get('square') else square(f, n)
    e = expdecay(n, 0.18 + 0.15 * acc)
    cut = 300 + (1500 + 2500 * acc) * e * (0.6 + 0.6 * vel)
    x = res_lp_sweep(raw, cut, q=7 + 6 * acc)
    x = soft(x * 0.7, 2.0)
    return stereo(x * adsr(n, 0.002, 0.05, 0.9, 0.03, int(dur * SR)))


def i_synth_bass_long(f, dur, vel, p):
    return i_sub(f, dur, vel, p)


def i_stab_organ(f, dur, vel, p):
    n = _len(dur, 0.12)
    x = sum(a * sine(f * h, n) for h, a in ((1, 1), (2, 0.6), (3, 0.35), (4, 0.25), (6, 0.12), (8, 0.08)))
    x = x * (0.7 + 0.3 * expdecay(n, 0.25))
    return stereo(x * adsr(n, 0.003, 0.15, 0.7, 0.1, int(dur * SR)) * 0.5, 0.6)


def i_stab_chord(f, dur, vel, p):
    n = _len(dur, 0.15)
    raw = detuned_stack(saw, f, n, voices=3, spread=0.12, seed=int(f))
    e = expdecay(n, 0.15)
    out = np.vstack([lp(raw[c], 600 + 4500 * e[0]) * 0.6 + bp(raw[c], 800, 3000) * 0.4 * e for c in range(2)])
    return out * adsr(n, 0.002, 0.1, 0.5, 0.12, int(dur * SR))


def i_supersaw(f, dur, vel, p):
    n = _len(dur, 0.25)
    raw = detuned_stack(saw, f, n, voices=7, spread=0.28, seed=int(f * 3))
    out = np.vstack([lp(hp(raw[c], 150), 7500) for c in range(2)])
    return out * adsr(n, 0.01, 0.2, 0.8, 0.22, int(dur * SR)) * 0.8


def i_pad_warm(f, dur, vel, p):
    n = _len(dur, 0.9)
    raw = detuned_stack(saw, f, n, voices=5, spread=0.18, seed=int(f * 7))
    raw += 0.35 * detuned_stack(saw, f * 0.5, n, voices=2, spread=0.05, seed=3)
    out = np.vstack([lp(raw[c], 1800, order=2) for c in range(2)])
    return out * adsr(n, 0.45, 0.5, 0.85, 0.85, int(dur * SR)) * 0.55


def i_pad_air(f, dur, vel, p):
    n = _len(dur, 1.2)
    t = _t(n)
    x = sum(sine(f * h * (1 + 0.0015 * k), n, phase=k) / h for k, h in enumerate((1, 2, 3, 4)))
    breath = bp(noise(n, int(f)), f * 2, f * 6) * 0.05
    trem = 1 + 0.06 * np.sin(2 * np.pi * 0.25 * t)
    m = (x * 0.5 + breath) * trem
    return stereo(m * adsr(n, 0.8, 0.6, 0.9, 1.1, int(dur * SR)) * 0.45, 0.8)


def i_strings(f, dur, vel, p):
    n = _len(dur, 0.5)
    t = _t(n)
    vib = f * (1 + 0.004 * np.sin(2 * np.pi * 5.2 * t) * np.clip(t / 0.4, 0, 1))
    raw = detuned_stack(lambda fr, n_, phase=0: saw(vib * fr / f, n_, phase=phase), f, n, voices=4, spread=0.1, seed=int(f))
    out = np.vstack([lp(hp(raw[c], 200), 3500) for c in range(2)])
    return out * adsr(n, 0.25, 0.3, 0.85, 0.45, int(dur * SR)) * 0.5


def i_epiano(f, dur, vel, p):
    """Rhodes-ish: two FM pairs (body + tine), velocity-sensitive bark, stereo tremolo."""
    n = _len(dur, 0.5)
    t = _t(n)
    i1 = (1.2 + 1.5 * vel) * expdecay(n, 0.8)
    body = np.sin(2 * np.pi * f * t + i1 * np.sin(2 * np.pi * f * t))
    tine = np.sin(2 * np.pi * f * t + 0.8 * expdecay(n, 0.05) * np.sin(2 * np.pi * 14 * f * t)) * expdecay(n, 0.4) * 0.3
    x = (body + tine) * expdecay(n, 2.5 + 200 / f)
    x *= adsr(n, 0.002, 0.1, 1.0, 0.35, int(dur * SR))
    trem = 0.5 + 0.5 * np.sin(2 * np.pi * 4.5 * t)
    return np.vstack([x * (0.75 + 0.25 * trem), x * (1.0 - 0.25 * trem)]) * 0.5


def i_keys_lofi(f, dur, vel, p):
    """Felt piano: inharmonic partials, soft hammer, dark, with a little wow."""
    n = _len(dur, 0.4)
    t = _t(n)
    wow = 1 + 0.0025 * np.sin(2 * np.pi * 0.7 * t)
    x = np.zeros(n)
    for h in range(1, 8):
        fh = f * h * math.sqrt(1 + 0.0004 * h * h)
        x += sine(fh * wow, n, phase=h) * (0.6 ** (h - 1)) * expdecay(n, (3.0 + 300 / f) / h ** 0.7)
    x = lp(x, 2600) * adsr(n, 0.004, 0.1, 1.0, 0.3, int(dur * SR))
    return stereo(x * 0.45, 0.4)


def i_pluck(f, dur, vel, p):
    n = _len(dur, 0.3)
    raw = detuned_stack(saw, f, n, voices=3, spread=0.1, seed=int(f * 5))
    e = expdecay(n, 0.25)
    out = np.vstack([lp(raw[c], 400) * (1 - e) * 0.3 + lp(raw[c], 5000) * e for c in range(2)])
    return out * expdecay(n, 0.9) * adsr(n, 0.001, 0.1, 1.0, 0.2, int(dur * SR)) * 0.75


def i_bell(f, dur, vel, p):
    n = _len(dur, 1.2)
    t = _t(n)
    x = np.sin(2 * np.pi * f * t + 1.8 * expdecay(n, 0.6) * np.sin(2 * np.pi * 3.5 * f * t))
    x += 0.3 * np.sin(2 * np.pi * 2 * f * t) * expdecay(n, 0.4)
    x *= expdecay(n, 1.6) * adsr(n, 0.001, 0.1, 1.0, 1.0, int(dur * SR))
    return stereo(x * 0.5, 0.5)


def i_mallet(f, dur, vel, p):
    n = _len(dur, 0.6)
    x = sine(f, n) * expdecay(n, 1.0) + 0.4 * sine(f * 4.0, n) * expdecay(n, 0.15) + 0.15 * sine(f * 10, n) * expdecay(n, 0.03)
    return stereo(x * adsr(n, 0.001, 0.1, 1.0, 0.5, int(dur * SR)) * 0.55, 0.4)


def i_lead_saw(f, dur, vel, p):
    n = _len(dur, 0.15)
    t = _t(n)
    vib = f * (1 + 0.006 * np.sin(2 * np.pi * 5.5 * t) * np.clip((t - 0.25) / 0.3, 0, 1))
    a = saw(vib, n)
    b = saw(vib * 1.006, n, phase=0.3)
    c = square(vib * 0.5, n, pw=0.45)
    x = lp(a + b + 0.4 * c, 4200)
    return stereo(x * adsr(n, 0.008, 0.2, 0.75, 0.12, int(dur * SR)) * 0.4, 0.5)


def i_arp_square(f, dur, vel, p):
    n = _len(dur, 0.1)
    x = square(f, n, pw=0.35) * 0.6 + square(f * 2.003, n, pw=0.5) * 0.2
    x = lp(x, 3500) * expdecay(n, 0.6)
    return stereo(x * adsr(n, 0.001, 0.08, 0.6, 0.08, int(dur * SR)) * 0.55, 0.5)


def i_guitar_clean(f, dur, vel, p):
    """Clean electric guitar: Karplus-Strong string (filtered noise burst through a tuned comb)."""
    n = _len(dur, 0.6)
    period = SR / f
    d = int(period)
    burst = lp(noise(d, int(f * 13)), 3000 + 3000 * vel)
    # feedback comb via repeated tiling with a one-pole low-pass each pass (vectorised per period)
    out = np.zeros(n)
    cur = burst
    decay = 0.996 ** (period / 50)
    pos = 0
    while pos < n:
        k = min(d, n - pos)
        out[pos:pos + k] = cur[:k]
        cur = 0.5 * (cur + np.roll(cur, 1)) * decay
        pos += d
    out = hp(out, 90)
    return stereo(out * adsr(n, 0.001, 0.05, 1.0, 0.25, int(dur * SR)) * 0.8, 0.3)


def i_surf_guitar(f, dur, vel, p):
    """Surf lead: bright single-coil twang into a hard clean amp with a drippy spring reverb tail."""
    x = i_guitar_clean(f, dur, vel, p)[0]
    n = len(x)
    x = soft(hp(x, 200) * 2.0, 1.5)
    # spring: a bank of chirpy dispersed echoes
    spring = np.zeros(n)
    for k, (dl, g) in enumerate(((0.031, 0.5), (0.047, 0.38), (0.071, 0.3), (0.093, 0.22), (0.127, 0.15))):
        s = int(dl * SR)
        if s < n:
            spring[s:] += g * bp(x[:-s], 1200 + 400 * k, 4500)
    t = _t(n)
    trem = 1 - 0.25 * (0.5 + 0.5 * np.sin(2 * np.pi * 6.0 * t)) * p.get('trem', 0)
    return np.vstack([(x + spring * 0.8) * trem, (x + np.roll(spring, 400) * 0.8) * trem]) * 0.6


def i_combo_organ(f, dur, vel, p):
    """60s transistor combo organ: thin buzzy pulse tones with a fast shallow vibrato."""
    n = _len(dur, 0.05)
    t = _t(n)
    vib = f * (1 + 0.005 * np.sin(2 * np.pi * 7 * t))
    x = square(vib, n, pw=0.25) * 0.5 + square(vib * 2, n, pw=0.4) * 0.3 + saw(vib * 4, n) * 0.08
    x = bp(x, 200, 5000)
    return stereo(x * adsr(n, 0.004, 0.05, 0.95, 0.04, int(dur * SR)) * 0.4, 0.6)


def i_bass_guitar(f, dur, vel, p):
    n = _len(dur, 0.06)
    x = saw(f, n) * 0.4 + sine(f, n)
    x = lp(x, 900 + 1500 * expdecay(n, 0.08)[0]) * expdecay(n, 1.5)
    pick = hp(noise(n, int(f)), 1500) * expdecay(n, 0.01) * 0.3
    return stereo(soft(x + pick, 1.3) * adsr(n, 0.002, 0.05, 1.0, 0.05, int(dur * SR)) * 0.9)


def _sum(*xs):
    n = max(x.shape[1] for x in xs)
    out = np.zeros((2, n))
    for x in xs:
        out[:, :x.shape[1]] += x
    return out


def i_baritone(f, dur, vel, p):
    return _sum(i_surf_guitar(f, dur, vel, dict(p, trem=0)) * 0.9, i_bass_guitar(f, dur, vel, p) * 0.5)


def i_horns(f, dur, vel, p):
    n = _len(dur, 0.12)
    t = _t(n)
    sw = np.clip(t / 0.06, 0, 1)
    raw = detuned_stack(saw, f, n, voices=3, spread=0.08, seed=int(f))
    out = np.vstack([res_lp_sweep(raw[c], 400 + 2600 * sw * (0.6 + 0.4 * vel), q=1.0) for c in range(2)])
    return out * adsr(n, 0.02, 0.15, 0.8, 0.1, int(dur * SR)) * 0.5


def i_guitar_space(f, dur, vel, p):
    """A clean guitar note frozen into a slow-blooming swell (Tycho-style)."""
    g = i_guitar_clean(f, dur, vel, p)
    n = g.shape[1]
    sw = np.clip(_t(n) / 0.35, 0, 1) ** 2
    return g * (0.35 + 0.65 * sw)


def i_piano(f, dur, vel, p):
    """Bright grand piano: stretched partials, hammer thump, two-stage decay, stereo by pitch."""
    n = _len(dur, 0.5)
    x = np.zeros(n)
    for h in range(1, 11):
        fh = f * h * math.sqrt(1 + 0.0003 * h * h)
        x += sine(fh, n, phase=h * 0.7) * (0.7 ** (h - 1)) * (0.6 * expdecay(n, (1.2 + 150 / f) / h ** 0.5) + 0.4 * expdecay(n, (5 + 400 / f) / h ** 0.6))
    x += lp(noise(n, int(f)), 1200) * expdecay(n, 0.02) * 0.15 * vel
    x *= adsr(n, 0.002, 0.1, 1.0, 0.3, int(dur * SR))
    pan = np.clip((math.log2(f / 261.6)) * 0.25, -0.6, 0.6)
    return np.vstack([x * (1 - pan) * 0.4, x * (1 + pan) * 0.4])


def i_flute(f, dur, vel, p):
    n = _len(dur, 0.15)
    t = _t(n)
    vib = f * (1 + 0.005 * np.sin(2 * np.pi * 5.0 * t) * np.clip((t - 0.2) / 0.3, 0, 1))
    x = sine(vib, n) + 0.25 * sine(vib * 2, n) + 0.08 * sine(vib * 3, n)
    breath = bp(noise(n, int(f)), f, f * 4) * 0.12
    return stereo((x + breath) * adsr(n, 0.06, 0.1, 0.85, 0.12, int(dur * SR)) * 0.4, 0.5)


def i_hoover(f, dur, vel, p):
    """Hard-dance screech / hoover: detuned PWM saws with a pitch scoop, distorted."""
    n = _len(dur, 0.1)
    t = _t(n)
    scoop = f * (1 - 0.06 * np.exp(-t / 0.05))
    raw = detuned_stack(lambda fr, n_, phase=0: saw(scoop * fr / f, n_, phase=phase), f, n, voices=5, spread=0.35, seed=int(f))
    raw += 0.5 * np.vstack([square(scoop * 0.5, n, pw=0.3)] * 2)
    out = np.vstack([soft(bp(raw[c], 300, 6000) * 1.4, 2.5) for c in range(2)])
    return out * adsr(n, 0.005, 0.1, 0.8, 0.08, int(dur * SR)) * 0.45


def i_cowbell_mel(f, dur, vel, p):
    """Pitched cowbell (Memphis phonk melody): two detuned square partials, band-passed, fast decay."""
    n = _len(dur, 0.25)
    t = _t(n)
    x = square(f, n, pw=0.5) * 0.6 + square(f * 1.48, n, pw=0.5) * 0.4
    x = bp(x, f * 0.8, min(f * 6, 9000)) * (0.6 * np.exp(-t / 0.03) + 0.4 * np.exp(-t / 0.22))
    return stereo(x * adsr(n, 0.001, 0.05, 1.0, 0.1, int(dur * SR)) * 0.55, 0.2)


# ------------------------------------------------------------------ drums
def _seedf(*a):
    return abs(hash(a)) % (2 ** 31)


def d_kick(kind, vel, p):
    spec = dict(
        kick_909=dict(f0=52, sweep=4.0, tau=0.035, decay=0.35, click=0.5, drive=1.4),
        kick_808=dict(f0=48, sweep=3.0, tau=0.04, decay=0.7, click=0.2, drive=1.1),
        kick_techno=dict(f0=48, sweep=5.0, tau=0.03, decay=0.45, click=0.6, drive=2.6),
        kick_soft=dict(f0=55, sweep=2.5, tau=0.04, decay=0.3, click=0.1, drive=1.0),
        kick_dnb=dict(f0=56, sweep=4.5, tau=0.025, decay=0.25, click=0.7, drive=1.6),
        kick_trap=dict(f0=50, sweep=4.0, tau=0.03, decay=0.3, click=0.6, drive=1.8),
        kick_deep=dict(f0=46, sweep=3.0, tau=0.04, decay=0.45, click=0.15, drive=1.2),
        kick_acoustic=dict(f0=60, sweep=2.0, tau=0.03, decay=0.25, click=0.4, drive=1.0),
    )[kind]
    n = int((spec['decay'] * 2 + 0.05) * SR)
    t = _t(n)
    f = spec['f0'] * (1 + spec['sweep'] * np.exp(-t / spec['tau']))
    body = sine(f, n) * np.exp(-t / spec['decay'] * 2.2)
    click = hp(noise(n, 7), 2000) * np.exp(-t / 0.004) * spec['click']
    x = soft(body + click, spec['drive'])
    if kind == 'kick_soft':
        x = lp(x, 3000)
    if kind == 'kick_acoustic':
        x = x + 0.25 * bp(noise(n, 8), 200, 1500) * np.exp(-t / 0.05)
    return stereo(x)


def d_snare(kind, vel, p):
    n = int(0.45 * SR)
    t = _t(n)
    if kind == 'snare_trap':
        tone = (sine(200 * (1 + 0.5 * np.exp(-t / 0.01)), n) * 0.7) * np.exp(-t / 0.06)
        nz = bp(noise(n, 11), 1500, 9000) * np.exp(-t / 0.09)
        x = tone + nz * 0.9
    elif kind == 'snare_dnb':
        tone = (sine(230 * (1 + 0.3 * np.exp(-t / 0.008)), n) + 0.5 * sine(400, n)) * np.exp(-t / 0.05)
        nz = bp(noise(n, 12), 2000, 10000) * np.exp(-t / 0.11)
        x = soft(tone * 0.8 + nz, 1.6)
    elif kind == 'snare_lofi':
        tone = sine(190, n) * np.exp(-t / 0.05)
        nz = bp(noise(n, 13), 800, 5000) * np.exp(-t / 0.12)
        x = lp(tone * 0.7 + nz * 0.8, 4000)
    elif kind == 'snare_gated':
        tone = sine(180 * (1 + 0.4 * np.exp(-t / 0.01)), n) * np.exp(-t / 0.08)
        nz = bp(noise(n, 14), 700, 9000)
        gate = (t < 0.22).astype(float) * np.exp(-t / 0.4)
        x = tone + nz * gate
    elif kind == 'snare_surf':
        tone = (sine(185, n) + 0.6 * sine(330, n)) * np.exp(-t / 0.05)
        rattle = bp(noise(n, 15), 1500, 7000) * np.exp(-t / 0.18)
        x = tone * 0.6 + rattle
    elif kind == 'snare_dub':
        tone = sine(170 * (1 + 0.3 * np.exp(-t / 0.01)), n) * np.exp(-t / 0.07)
        nz = bp(noise(n, 16), 900, 6000) * np.exp(-t / 0.16)
        x = soft(tone + nz * 0.9, 1.3)
    else:  # snare_909
        tone = (sine(185, n) + 0.6 * sine(330, n)) * np.exp(-t / 0.04)
        nz = bp(noise(n, 17), 1200, 9000) * np.exp(-t / 0.1)
        x = tone * 0.7 + nz
    return stereo(x * 0.8, 0.2)


def d_clap(kind, vel, p):
    n = int(0.5 * SR)
    t = _t(n)
    nz = bp(noise(n, 21), 900, 6000)
    env = np.zeros(n)
    for k, dt in enumerate((0, 0.011, 0.022, 0.031)):
        m = t >= dt
        env[m] += np.exp(-(t[m] - dt) / 0.006) * (0.7 if k < 3 else 1)
    tail = np.exp(-np.maximum(t - 0.031, 0) / (0.16 if kind == 'clap_big' else 0.09)) * (t >= 0.031)
    x = nz * (env + tail * 0.8)
    return stereo(x * 0.7, 0.7 if kind == 'clap_big' else 0.4)


_HAT_F = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)


def d_hat(kind, vel, p):
    open_ = kind.startswith('ohat')
    dec = {'hat_909': 0.045, 'hat_808': 0.05, 'hat_lofi': 0.04, 'hat_trap': 0.035, 'ohat_909': 0.28, 'hat_surf': 0.06}.get(kind, 0.05)
    n = int((dec * 4 + 0.02) * SR)
    t = _t(n)
    metal = sum(square(f * 1.0, n, pw=0.5) for f in _HAT_F) / 6
    nz = noise(n, 31)
    x = hp(metal * 0.6 + nz * 0.6, 7000 if not open_ else 6500, order=4)
    x *= np.exp(-t / dec)
    if kind == 'hat_lofi':
        x = lp(x, 7000)
    return stereo(x * 0.45, 0.3)


def d_ride(kind, vel, p):
    n = int(1.4 * SR)
    t = _t(n)
    metal = sum(square(f * 2.7, n, pw=0.5) for f in _HAT_F) / 6
    x = hp(metal * 0.5 + noise(n, 41) * 0.25, 4000) * np.exp(-t / 0.5)
    x += 0.2 * sine(3200, n) * np.exp(-t / 0.3)
    return stereo(x * 0.3, 0.5)


def d_shaker(kind, vel, p):
    n = int(0.12 * SR)
    t = _t(n)
    env = np.clip(t / 0.012, 0, 1) * np.exp(-t / 0.035)
    return stereo(hp(noise(n, 51), 5000) * env * 0.3, 0.6)


def d_rim(kind, vel, p):
    n = int(0.1 * SR)
    t = _t(n)
    x = bp(noise(n, 61), 1500, 4000) * np.exp(-t / 0.006) + sine(1700, n) * np.exp(-t / 0.015) * 0.5
    return stereo(x * 0.6)


def d_perc(kind, vel, p, f=None):
    n = int(0.5 * SR)
    t = _t(n)
    if kind == 'perc_conga':
        f0 = f or 220
        x = sine(f0 * (1 + 0.4 * np.exp(-t / 0.01)), n) * np.exp(-t / 0.12) + 0.2 * bp(noise(n, 71), 800, 3000) * np.exp(-t / 0.01)
    else:  # perc_tom
        f0 = f or 110
        x = sine(f0 * (1 + 0.8 * np.exp(-t / 0.02)), n) * np.exp(-t / 0.2)
    return stereo(x * 0.6, 0.2)


def d_cowbell(kind, vel, p):
    n = int(0.35 * SR)
    t = _t(n)
    x = square(540, n, pw=0.5) * 0.6 + square(800, n, pw=0.5) * 0.4
    x = bp(x, 600, 3500) * (0.65 * np.exp(-t / 0.02) + 0.35 * np.exp(-t / 0.18))
    return stereo(x * 0.45, 0.2)


def d_crash(kind, vel, p):
    n = int(2.2 * SR)
    t = _t(n)
    metal = sum(square(f * 3.1, n, pw=0.5) for f in _HAT_F) / 6
    x = hp(metal * 0.4 + noise(n, 81) * 0.6, 3500) * np.exp(-t / 0.9)
    return stereo(x * 0.35, 0.8)


# ------------------------------------------------------------------ fx
def fx(kind, dur, vel, p):
    n = int((dur + 0.6) * SR)
    t = _t(n)
    d = max(dur, 0.1)
    if kind == 'riser':
        prog = np.clip(t / d, 0, 1)
        nz = noise(n, 91)
        y = res_lp_sweep(nz, 300 + 9000 * prog ** 2, q=2.5)
        tone = saw(200 * 2 ** (prog * 3), n) * 0.12
        x = (y * 0.5 + lp(tone, 6000)) * prog ** 1.5 * (t < d)
        return stereo(x, 0.9)
    if kind == 'downlifter':
        prog = np.clip(t / d, 0, 1)
        y = res_lp_sweep(noise(n, 92), 9000 * (1 - prog) ** 2 + 200, q=2.0)
        return stereo(y * (1 - prog) * 0.5, 0.9)
    if kind == 'impact':
        boom = sine(45 * (1 + 2 * np.exp(-t / 0.05)), n) * np.exp(-t / 0.6)
        x = soft(boom * 1.2, 1.5) + lp(noise(n, 93), 1500) * np.exp(-t / 0.4) * 0.3
        return stereo(x * 0.8, 0.6)
    if kind == 'revcrash':
        c = d_crash('crash', vel, p)
        m = int(d * SR)
        r = c[:, :m][:, ::-1]
        out = np.zeros((2, n))
        out[:, :r.shape[1]] = r
        return out
    if kind == 'crash':
        return d_crash('crash', vel, p)
    if kind == 'vinyl':
        rng = np.random.default_rng(int(dur * 10))
        x = lp(noise(n, 94), 3000) * 0.015
        pops = rng.random(n) < 6 / SR
        x[pops] += rng.choice([-1, 1], pops.sum()) * rng.random(pops.sum()) * 0.5
        return stereo(x, 0.5)
    return np.zeros((2, n))


MELODIC = {
    'bass_sub': i_sub, 'bass_organ': i_organ_bass, 'bass_pluck': i_bass_pluck, 'bass_synth': i_bass_synth, 'bass_fm': i_bass_fm,
    'bass_reese': i_reese, 'bass_wobble': i_wobble, 'bass_808': i_808, 'bass_acid': i_acid, 'bass_guitar': i_bass_guitar,
    'stab_organ': i_stab_organ, 'stab_chord': i_stab_chord, 'supersaw': i_supersaw, 'pad_warm': i_pad_warm, 'pad_air': i_pad_air,
    'strings': i_strings, 'keys_epiano': i_epiano, 'keys_lofi': i_keys_lofi, 'pluck': i_pluck, 'bell': i_bell, 'mallet': i_mallet,
    'lead_saw': i_lead_saw, 'arp_square': i_arp_square, 'guitar_clean': i_guitar_clean, 'surf_guitar': i_surf_guitar,
    'combo_organ': i_combo_organ, 'baritone': i_baritone, 'horns': i_horns, 'guitar_space': i_guitar_space,
    'piano': i_piano, 'flute': i_flute, 'hoover': i_hoover, 'cowbell_mel': i_cowbell_mel,
}
DRUMS = {}
for k in ('kick_909', 'kick_808', 'kick_techno', 'kick_soft', 'kick_dnb', 'kick_trap', 'kick_deep', 'kick_acoustic'):
    DRUMS[k] = d_kick
for k in ('snare_909', 'snare_dnb', 'snare_lofi', 'snare_trap', 'snare_gated', 'snare_surf', 'snare_dub'):
    DRUMS[k] = d_snare
for k in ('clap_909', 'clap_big'):
    DRUMS[k] = d_clap
for k in ('hat_909', 'hat_808', 'hat_lofi', 'hat_trap', 'ohat_909', 'hat_surf'):
    DRUMS[k] = d_hat
DRUMS.update(cowbell=d_cowbell, ride=d_ride, shaker=d_shaker, rim=d_rim, perc_conga=d_perc, perc_tom=d_perc, crash=d_crash)

LABELS = {
    'bass_sub': 'Sub bass', 'bass_organ': 'Organ bass', 'bass_pluck': 'Pluck bass', 'bass_synth': 'Analog saw bass', 'bass_fm': 'FM bass',
    'bass_reese': 'Reese', 'bass_wobble': 'Wobble', 'bass_808': '808', 'bass_acid': 'Acid 303', 'bass_guitar': 'Bass guitar',
    'stab_organ': 'Organ stab', 'stab_chord': 'Saw stab', 'supersaw': 'Supersaw', 'pad_warm': 'Warm pad', 'pad_air': 'Air pad',
    'strings': 'Strings', 'keys_epiano': 'Electric piano', 'keys_lofi': 'Felt piano', 'pluck': 'Pluck', 'bell': 'FM bell',
    'mallet': 'Mallet', 'lead_saw': 'Saw lead', 'arp_square': 'Square arp', 'guitar_clean': 'Clean guitar', 'surf_guitar': 'Surf guitar',
    'combo_organ': 'Combo organ', 'baritone': 'Baritone twang', 'horns': 'Horn section', 'guitar_space': 'Space guitar',
    'piano': 'Grand piano', 'flute': 'Flute', 'hoover': 'Hoover screech', 'cowbell_mel': 'Cowbell melody',
}
ROLE_CHOICES = {
    'bass': ['bass_sub', 'bass_organ', 'bass_pluck', 'bass_synth', 'bass_fm', 'bass_reese', 'bass_wobble', 'bass_808', 'bass_acid', 'bass_guitar'],
    'chords': ['stab_organ', 'stab_chord', 'supersaw', 'pad_warm', 'pad_air', 'strings', 'keys_epiano', 'keys_lofi', 'pluck', 'guitar_clean', 'combo_organ', 'horns', 'guitar_space', 'piano'],
    'pad': ['pad_warm', 'pad_air', 'strings', 'supersaw', 'guitar_space'],
    'lead': ['pluck', 'bell', 'mallet', 'lead_saw', 'supersaw', 'arp_square', 'surf_guitar', 'horns', 'keys_epiano', 'guitar_clean', 'combo_organ', 'piano', 'flute', 'hoover', 'cowbell_mel'],
    'arp': ['pluck', 'bell', 'mallet', 'arp_square', 'keys_epiano', 'guitar_clean', 'guitar_space'],
    'answer': ['bell', 'mallet', 'pluck', 'arp_square', 'keys_epiano', 'flute', 'guitar_clean', 'piano'],
    'riff': ['baritone', 'surf_guitar', 'bass_guitar', 'lead_saw', 'bass_synth'],
}


def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)


@functools.lru_cache(maxsize=4096)
def _cached(inst, midi, vel_q, dur_q, pkey):
    p = dict(pkey)
    vel = vel_q / 16
    dur = dur_q / 200
    if inst in DRUMS:
        fn = DRUMS[inst]
        if fn is d_perc:
            x = d_perc(inst, vel, p, f=mtof(midi) if midi else None)
        else:
            x = fn(inst, vel, p)
    elif inst == 'fx':
        x = fx(p.get('kind', 'riser'), dur, vel, p)
    else:
        x = MELODIC[inst](mtof(midi), dur, vel, p)
    x = np.asarray(x, dtype=np.float32)
    x.setflags(write=False)
    return x


def play(inst, midi, dur, vel, p=None):
    """One note -> (2, n) float32. Results are cached (same sound, pitch, length and velocity = same audio)."""
    p = p or {}
    pkey = tuple(sorted((k, v) for k, v in p.items() if isinstance(v, (int, float, str, bool))))
    vel_q = max(1, min(16, int(round(vel * 16))))
    x = _cached(inst, int(round(midi)), vel_q, max(1, int(round(dur * 200))), pkey)
    return x * (0.25 + 0.75 * vel_q / 16)


def known(inst):
    return inst in MELODIC or inst in DRUMS or inst == 'fx'
