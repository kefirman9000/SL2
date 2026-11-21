"""Reference-track analysis: measure a real song so a genre can be modelled on it, or matched to it.

Measured: tempo, key, harmonic rhythm and chord loop, the drum pattern folded onto one bar (kick / snare / hats),
how the energy moves bar by bar (intro length, breakdowns, drops), tonal balance in 9 bands, loudness, stereo width,
low-end mono, and sidechain pumping depth.

Audio is read with ffmpeg when it's installed (MP3, WMA, M4A, FLAC ...), otherwise WAV only.
"""
import os
import shutil
import subprocess
import wave

import numpy as np
from scipy import signal

SR = 22050
HOP = 256
BANDS = [(20, 60), (60, 120), (120, 250), (250, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 8000), (8000, 11000)]
MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']


class AnalysisError(RuntimeError):
    pass


# ------------------------------------------------------------------ reading audio
def load(path, sr=SR, stereo=True):
    """-> float32 array (2, n) at sr."""
    if shutil.which('ffmpeg'):
        cmd = ['ffmpeg', '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '2', '-ar', str(sr), '-']
        p = subprocess.run(cmd, capture_output=True)
        if p.returncode != 0 or not p.stdout:
            raise AnalysisError('could not read the file: ' + p.stderr.decode(errors='replace')[-300:])
        x = np.frombuffer(p.stdout, dtype=np.float32).reshape(-1, 2).T.copy()
    else:
        if not path.lower().endswith('.wav'):
            raise AnalysisError('only WAV files can be read without ffmpeg - install ffmpeg for MP3 and others')
        with wave.open(path, 'rb') as w:
            ch, sw, fr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(n)
        if sw == 2:
            a = np.frombuffer(raw, '<i2').astype(np.float32) / 32768
        elif sw == 3:
            b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
            a = ((b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16)) << 8 >> 8) / 8388608.0
            a = a.astype(np.float32)
        elif sw == 4:
            a = np.frombuffer(raw, '<i4').astype(np.float32) / 2147483648
        else:
            raise AnalysisError(f'unsupported WAV sample width {sw}')
        a = a.reshape(-1, ch).T
        if ch == 1:
            a = np.vstack([a, a])
        x = a[:2]
        if fr != sr:
            from math import gcd
            g = gcd(fr, sr)
            x = signal.resample_poly(x, sr // g, fr // g, axis=1).astype(np.float32)
    if not stereo:
        x = x.mean(0)
    return x


# ------------------------------------------------------------------ helpers
def _stft_mag(mono, n_fft=2048, hop=HOP):
    f, t, Z = signal.stft(mono, fs=SR, nperseg=n_fft, noverlap=n_fft - hop, boundary=None, padded=False)
    return f, np.abs(Z).astype(np.float32)


def _band_env(M, f, lo, hi):
    idx = (f >= lo) & (f < hi)
    return M[idx].sum(0)


def _onset(env):
    """Half-wave-rectified log-energy rise."""
    e = np.log1p(env * 100 / (env.max() + 1e-9))
    d = np.diff(e, prepend=e[0])
    d[d < 0] = 0
    return d


def tempo_of(onset, lo=60, hi=200, prefer=None):
    """Tempo from the autocorrelation of the onset curve, with a gentle preference for 90-180 BPM
    (or around `prefer`)."""
    o = onset - onset.mean()
    ac = signal.fftconvolve(o, o[::-1], mode='full')[len(o) - 1:]
    fps = SR / HOP
    best, best_s = None, -1e9
    center = prefer or 125
    for bpm10 in range(lo * 10, hi * 10 + 1, 2):
        bpm = bpm10 / 10
        lag = 60 * fps / bpm
        i = int(lag)
        if i + 1 >= len(ac):
            continue
        v = ac[i] * (1 - (lag - i)) + ac[i + 1] * (lag - i)
        # harmonics: a real beat also correlates at 2x and 4x its period
        for k in (2, 4):
            j = int(lag * k)
            if j + 1 < len(ac):
                v += 0.5 * ac[j]
        w = np.exp(-0.5 * (np.log2(bpm / center) / (0.3 if prefer else 0.9)) ** 2)
        s = v * w
        if s > best_s:
            best, best_s = bpm, s
    return best


def key_of(chroma_sum):
    best = None
    for r in range(12):
        for name, prof in (('major', MAJ), ('minor', MIN)):
            c = np.corrcoef(np.roll(prof, r), chroma_sum)[0, 1]
            if best is None or c > best[0]:
                best = (c, r, name)
    return best[1], best[2], float(best[0])


def chroma_frames(M, f):
    ok = (f > 55) & (f < 2000)
    pcs = np.round(12 * np.log2(f[ok] / 440.0) + 69).astype(int) % 12
    C = np.zeros((12, M.shape[1]), np.float32)
    Mm = M[ok] ** 2
    for pc in range(12):
        C[pc] = Mm[pcs == pc].sum(0)
    return C


def lufs(x, sr):
    """Integrated loudness (ITU-R BS.1770, gated) of a stereo float signal."""
    b1, a1 = _shelf(sr)
    b2, a2 = signal.butter(2, 38.0 / (sr / 2), 'high')
    y = signal.lfilter(b2, a2, signal.lfilter(b1, a1, x, axis=-1), axis=-1)
    blk, step = int(0.4 * sr), int(0.1 * sr)
    e = (y.astype(np.float64) ** 2).sum(0)
    c = np.concatenate([[0.0], np.cumsum(e)])
    starts = np.arange(0, y.shape[1] - blk, step)
    ms = (c[starts + blk] - c[starts]) / blk
    if not len(ms):
        return -70.0
    L = -0.691 + 10 * np.log10(ms + 1e-12)
    g = ms[L > -70]
    if not len(g):
        return -70.0
    rel = -0.691 + 10 * np.log10(g.mean()) - 10
    g2 = ms[(L > -70) & (L > rel)]
    return float(-0.691 + 10 * np.log10(g2.mean() + 1e-12))


def _shelf(sr, f0=1681.97, gain=3.99984, q=0.7071752):
    A = 10 ** (gain / 40)
    w = 2 * np.pi * f0 / sr
    al = np.sin(w) / (2 * q)
    c = np.cos(w)
    b = np.array([A * ((A + 1) + (A - 1) * c + 2 * np.sqrt(A) * al), -2 * A * ((A - 1) + (A + 1) * c),
                  A * ((A + 1) + (A - 1) * c - 2 * np.sqrt(A) * al)])
    a = np.array([(A + 1) - (A - 1) * c + 2 * np.sqrt(A) * al, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - 2 * np.sqrt(A) * al])
    return b / a[0], a / a[0]


# ------------------------------------------------------------------ the analysis
def analyze(path, bpm_hint=None):
    x = load(path)
    if x.shape[1] < SR * 5:
        raise AnalysisError('the file is shorter than 5 seconds')
    mono = x.mean(0)
    dur = x.shape[1] / SR
    f, M = _stft_mag(mono)
    fps = SR / HOP
    low = _band_env(M, f, 30, 120)
    mid = _band_env(M, f, 150, 2500)
    high = _band_env(M, f, 6000, 11000)
    full = M.sum(0)
    on_low, on_mid, on_high = _onset(low), _onset(mid), _onset(high)
    onset = on_low + on_mid + 0.5 * on_high
    bpm = tempo_of(onset, prefer=bpm_hint)
    beat = 60 / bpm
    bar = 4 * beat
    # fine tempo + grid phase: the 16th grid that lines up best with all onsets over the whole song
    weights = np.array([1.0, 0.3, 0.6, 0.3] * 4)
    best = (-1, bpm, 0.0)
    for b in np.arange(bpm - 1.0, bpm + 1.0001, 0.02):
        st = 60 / b / 4 * fps
        n_s = int((len(onset) - 2) / st) - 1
        idx_f = np.arange(n_s) * st
        for ph in np.arange(0, st * 4, st / 4):
            ii = (idx_f + ph).astype(int)
            ii = ii[ii < len(onset)]
            w = weights[np.arange(len(ii)) % 4 * 4 % 16]
            sc = float((onset[ii] * w).mean())
            if sc > best[0]:
                best = (sc, b, ph)
    _, bpm, ph0 = best
    beat = 60 / bpm
    bar = 4 * beat
    step_fr = beat / 4 * fps
    n_steps = int(len(onset) / step_fr) - 1
    bar_fr0 = 16 * step_fr
    nb0 = int((len(onset) - ph0) / bar_fr0)
    low_bar = np.array([low[int(ph0 + b * bar_fr0):int(ph0 + (b + 1) * bar_fr0)].mean() for b in range(nb0)]) if nb0 else np.zeros(1)
    loud_bars = set(np.nonzero(low_bar > 0.5 * np.percentile(low_bar, 90))[0].tolist())

    def fold(o, phase):
        steps = np.zeros(16)
        cnt = np.zeros(16)
        for s_ in range(n_steps):
            if (s_ // 16) not in loud_bars:
                continue
            i = int(round(phase + s_ * step_fr))
            if i + 2 >= len(o):
                break
            steps[s_ % 16] += o[i:i + 3].max()
            cnt[s_ % 16] += 1
        return steps / np.maximum(cnt, 1)
    # which of the 4 beats is the downbeat: the one with the strongest kick
    best_phase, best_v = ph0, -1
    for k in range(4):
        ph = ph0 + k * 4 * step_fr
        kk = fold(on_low, ph)
        v = kk[0] + 0.5 * kk[8] - 0.2 * kk.mean()
        if v > best_v:
            best_v, best_phase = v, ph
    kick = fold(on_low, best_phase)
    snare = fold(on_mid, best_phase)
    hats = fold(on_high, best_phase)

    def contrast(v):
        lo_, hi_ = np.percentile(v, 15), v.max()
        return np.clip((v - lo_) / (hi_ - lo_ + 1e-9), 0, 1)
    kick, snare, hats = contrast(kick), contrast(snare), contrast(hats)

    def pattern(v):
        return ''.join('X' if a > 0.75 else 'x' if a > 0.5 else 'o' if a > 0.3 else '.' for a in v)

    # ---- bar-by-bar energy: where things come in and drop out
    bar_fr = bar * fps
    nb = int(len(full) / bar_fr)
    p0 = best_phase
    bars = []
    for b in range(nb):
        i0, i1 = int(p0 + b * bar_fr), int(p0 + (b + 1) * bar_fr)
        if i1 > len(full):
            break
        bars.append((float(low[i0:i1].mean()), float(mid[i0:i1].mean()), float(high[i0:i1].mean()), float(full[i0:i1].mean())))
    B = np.array(bars) if bars else np.zeros((1, 4))
    ref_low = np.percentile(B[:, 0], 90) + 1e-9
    ref_all = np.percentile(B[:, 3], 90) + 1e-9
    low_on = B[:, 0] / ref_low > 0.35
    level_db = 20 * np.log10(B[:, 3] / ref_all + 1e-6)
    intro_bars = int(np.argmax(low_on)) if low_on.any() else 0
    # sections: runs of bars with the low end on / off, at least 4 bars long
    runs = []
    cur, start = None, 0
    for i, on in enumerate(low_on):
        if on != cur:
            if cur is not None:
                runs.append((start, i - start, bool(cur)))
            cur, start = on, i
    runs.append((start, len(low_on) - start, bool(cur)))
    merged = []
    for r in runs:
        if merged and (r[1] < 4 or merged[-1][2] == r[2]):
            s, n, on = merged[-1]
            merged[-1] = (s, n + r[1], on)
        else:
            merged.append(r)
    sections = [dict(start_bar=s, bars=n, low_end=on, level_db=round(float(level_db[s:s + n].mean()), 1)) for s, n, on in merged]

    # ---- key and chords
    C = chroma_frames(M, f)
    k_root, k_scale, k_conf = key_of(C.sum(1))
    chords = []
    for b in range(min(len(bars), 400)):
        i0, i1 = int(p0 + b * bar_fr), int(p0 + (b + 1) * bar_fr)
        c = C[:, i0:i1].sum(1)
        best = None
        for r in range(12):
            for q, iv in (('', (0, 4, 7)), ('m', (0, 3, 7))):
                tpl = np.zeros(12)
                tpl[[(r + i) % 12 for i in iv]] = 1
                s = float(np.dot(tpl, c) / (np.linalg.norm(c) + 1e-9))
                if best is None or s > best[0]:
                    best = (s, NAMES[r] + q)
        chords.append(best[1])
    changes = sum(1 for a, b in zip(chords, chords[1:]) if a != b)
    harmonic_rhythm = round(len(chords) / max(1, changes), 1) if chords else 0
    # the commonest 4-chord loop in the loud sections
    loops = {}
    loud = [i for i, s in enumerate(low_on) if s]
    for i in loud:
        seq = []
        j = i
        while j < len(chords) and len(seq) < 4:
            if not seq or chords[j] != seq[-1]:
                seq.append(chords[j])
            j += 1
        if len(seq) == 4:
            loops[tuple(seq)] = loops.get(tuple(seq), 0) + 1
    loop = list(max(loops, key=loops.get)) if loops else chords[:4]

    # ---- tone, loudness, width, pumping
    full_sr = load(path, sr=44100) if dur < 900 else None
    loud_lufs = lufs(full_sr, 44100) if full_sr is not None else None
    peak = float(20 * np.log10(np.abs(x).max() + 1e-9))
    spec = (M ** 2).mean(1)
    tone = []
    for lo, hi in BANDS:
        idx = (f >= lo) & (f < hi)
        tone.append(10 * np.log10(spec[idx].sum() + 1e-12))
    tone = np.array(tone)
    tone = np.round(tone - tone.max(), 1).tolist()
    mid_s, side_s = (x[0] + x[1]) / 2, (x[0] - x[1]) / 2
    width = float(np.sqrt((side_s ** 2).mean() / ((mid_s ** 2).mean() + 1e-12)))
    sos = signal.butter(4, 120 / (SR / 2), 'low', output='sos')
    lo_m, lo_s = signal.sosfilt(sos, mid_s), signal.sosfilt(sos, side_s)
    low_side_db = float(10 * np.log10((lo_s ** 2).mean() / ((lo_m ** 2).mean() + 1e-12) + 1e-12))
    # pumping: the pads / mids (300-3000 Hz, kick-free) folded onto the beat
    pump_env = _band_env(M, f, 300, 3000)
    beat_fr = beat * fps
    nbt = int((len(pump_env) - p0) / beat_fr) - 1
    fold_b = np.zeros(8)
    for bt in range(nbt):
        for k in range(8):
            i = int(p0 + bt * beat_fr + k * beat_fr / 8)
            if i < len(pump_env):
                fold_b[k] += pump_env[i]
    fold_b = fold_b / max(nbt, 1)
    pump_db = float(20 * np.log10((fold_b.max() + 1e-9) / (fold_b.min() + 1e-9)))
    centroid = float((f[:, None] * M).sum(0).mean() / (M.sum(0).mean() + 1e-9))
    rms_db = float(20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9))

    return dict(
        file=os.path.basename(path), duration=round(dur, 1), bpm=round(bpm, 1),
        key=f'{NAMES[k_root]} {k_scale}', key_root=k_root, key_scale=k_scale, key_confidence=round(k_conf, 2),
        drums=dict(kick=pattern(kick), snare=pattern(snare), hats=pattern(hats),
                   kick_raw=np.round(kick, 2).tolist(), snare_raw=np.round(snare, 2).tolist(), hats_raw=np.round(hats, 2).tolist()),
        bars=len(bars), intro_bars=intro_bars, sections=sections,
        chords_first_32=chords[:32], chord_loop=loop, harmonic_rhythm_bars=harmonic_rhythm,
        lufs=None if loud_lufs is None else round(loud_lufs, 1), peak_db=round(peak, 1),
        plr_db=None if loud_lufs is None else round(peak - loud_lufs, 1),
        tone=tone, centroid_hz=round(centroid), width=round(width, 2), low_side_db=round(low_side_db, 1),
        pump_db=round(pump_db, 1), rms_db=round(rms_db, 1),
    )


# ------------------------------------------------------------------ matching a reference to a genre
def match_genres(a, genres):
    """Rank genres by how well a reference's measurements fit them. -> [(score, genre_id, reasons)]"""
    out = []
    for gid, g in genres.items():
        lo, hi = g['bpm']
        bpm = a['bpm']
        cands = [bpm, bpm / 2, bpm * 2]
        d = min(0 if lo <= b <= hi else min(abs(b - lo), abs(b - hi)) for b in cands)
        s = -d / 3.0
        fit_bpm = min(cands, key=lambda b: 0 if lo <= b <= hi else min(abs(b - lo), abs(b - hi)))
        reasons = [f"tempo {fit_bpm:.0f} BPM fits {lo}-{hi}" if d == 0 else f"tempo is {d:.0f} BPM outside {lo}-{hi}"]
        fp = g.get('fingerprint') or {}
        if fp.get('tone'):
            diff = np.abs(np.array(fp['tone']) - np.array(a['tone'])).mean()
            s -= diff / 2.5
            reasons.append(f'tonal balance differs by {diff:.1f} dB on average')
        if fp.get('kick'):
            k1 = np.array(fp['kick'])
            k2 = np.array(a['drums']['kick_raw'])
            if len(k1) == len(k2):
                s += 2 * float(np.dot(k1, k2) / (np.linalg.norm(k1) * np.linalg.norm(k2) + 1e-9))
                reasons.append('kick pattern ' + ('matches' if np.dot(k1, k2) / (np.linalg.norm(k1) * np.linalg.norm(k2) + 1e-9) > 0.8 else 'differs'))
        if fp.get('pump_db') is not None:
            s -= abs(fp['pump_db'] - a['pump_db']) / 4
        out.append((round(s, 2), gid, reasons, round(fit_bpm, 1)))
    return sorted(out, reverse=True)
