"""Rendering: song document -> one stereo stem per track (in parallel, cached) -> mix -> master.

Stems are cached by a hash of everything that shapes them (notes, sound, effects, tempo, length), so changing one
part re-renders only that part, and mixer moves (level, pan, mute, solo) re-use every stem: a remix takes a second.

Smart parts:
  auto-gain    each stem is measured and set to a target level for its role before you touch a fader
  sidechain    ducking computed from the kick's actual note times
  ref master   the master EQ, stereo width, low-end mono and loudness are steered toward the genre's
               fingerprint (measured from the reference tracks the genre was modelled on)
"""
import atexit
import functools
import hashlib
import json
import os
import threading
import time
import wave
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

import numpy as np
from scipy import signal
from scipy.ndimage import minimum_filter1d, uniform_filter1d

from . import genres as G
from . import synth
from .analyze import BANDS, lufs

SR = synth.SR
ENGINE = 'sl2-engine-1'
ROLE_TARGET = {'kick': -14, 'snare': -17.5, 'clap': -19, 'hat': -28, 'ohat': -28, 'ride': -30, 'shaker': -31, 'perc': -26,
               'rim': -27, 'cowbell': -26, 'bass': -15.5, 'riff': -18, 'chords': -21, 'pad': -25, 'lead': -19, 'arp': -24, 'answer': -24,
               'fx': -28}
MONO_ROLES = {'bass', 'riff'}
DRUMS = {'kick', 'snare', 'clap', 'hat', 'ohat', 'ride', 'shaker', 'perc', 'rim', 'cowbell'}


# ------------------------------------------------------------------ space (reverb impulse responses)
@functools.lru_cache(maxsize=8)
def impulse(space):
    t60 = {'room': 0.7, 'plate': 1.5, 'hall': 2.7}.get(space, 1.5)
    n = int(t60 * 1.2 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)
    out = []
    for ch in range(2):
        nz = rng.standard_normal(n)
        lo = signal.sosfilt(signal.butter(2, 500 / (SR / 2), 'low', output='sos'), nz) * np.exp(-6.9 * t / (t60 * 1.15))
        mid = signal.sosfilt(signal.butter(2, [500 / (SR / 2), 4000 / (SR / 2)], 'band', output='sos'), nz) * np.exp(-6.9 * t / t60)
        hi = signal.sosfilt(signal.butter(2, 4000 / (SR / 2), 'high', output='sos'), nz) * np.exp(-6.9 * t / (t60 * 0.45))
        x = lo * 0.8 + mid + hi * (0.8 if space == 'plate' else 0.5)
        pre = int(0.012 * SR)
        x = np.concatenate([np.zeros(pre), x])[:n]
        x *= np.clip(t / 0.03, 0, 1) ** 0.5           # soft onset (less "clicky" early field)
        out.append(x)
    ir = np.vstack(out)
    return (ir / np.sqrt((ir ** 2).sum(1, keepdims=True).mean()) * 0.35).astype(np.float32)


# ------------------------------------------------------------------ building render specs
def _beat_s(song):
    return 60.0 / song.bpm


def track_specs(song):
    g = G.load(song.genre)
    bs = _beat_s(song)
    total = song.total_bars() * 4 * bs
    kick = []
    for t in song.tracks:
        if t.role == 'kick' and not t.muted:
            kick += [round(n.beat * bs, 5) for n in song.notes_of(t.id)]
    sc = g.get('sidechain', {})
    specs = []
    for t in song.tracks:
        notes = [(round(n.beat * bs, 5), round(n.length * bs, 5), n.pitch, round(n.velocity, 3), n.p) for n in song.notes_of(t.id)]
        pr = t.params
        auto = {k: [[round(a * bs, 5), round(b * bs, 5), float(f0), float(f1)] for a, b, f0, f1 in v]
                for k, v in (t.automation or {}).items() if k in ('lp', 'hp') and v}
        spec = dict(engine=ENGINE, id=t.id, role=t.role, inst=t.instrument, notes=notes, total=round(total, 4),
                    rev=float(pr.get('rev', 0)), dly=float(pr.get('dly', 0)), level=float(pr.get('level', 0)),
                    width=float(pr.get('width', 0)), pan=float(t.pan), space=g.get('space', 'plate'),
                    beat=round(bs, 6), sc=float(pr.get('sc', 1.0 if t.role in ('bass', 'chords', 'pad', 'arp', 'riff') else 0)),
                    sc_depth=float(sc.get('depth', 0)), sc_release=float(sc.get('release', 0.45)),
                    kicks=kick if t.role != 'kick' and sc.get('depth', 0) > 0 else [])
        if auto:
            spec['auto'] = auto
        chain = pr.get('fx') or []
        if chain:
            spec['fx'] = chain
            if any(c[0] in ('stutter', 'reverse') for c in chain):
                spec['secs'] = [[round(x.start_bar * 4 * bs, 5), round((x.start_bar + x.bars) * 4 * bs, 5)] for x in song.sections]
        spec['hash'] = hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:20]
        specs.append(spec)
    return specs


# ------------------------------------------------------------------ one track (runs in a worker process)
def _krms_db(x):
    """K-weighted RMS (dB) over the parts of the track that are actually sounding."""
    from .analyze import _shelf
    b1, a1 = _shelf(SR)
    b2, a2 = signal.butter(2, 38.0 / (SR / 2), 'high')
    m = x.mean(0)
    y = signal.lfilter(b2, a2, signal.lfilter(b1, a1, m))
    win = int(0.05 * SR)
    p = uniform_filter1d(y ** 2, win)
    on = p > (10 ** (-60 / 10))
    if on.sum() < SR * 0.05:
        return -120.0
    return float(10 * np.log10(p[on].mean() + 1e-12))


def render_track(spec):
    n_total = int((spec['total'] + 4.0) * SR)
    buf = np.zeros((2, n_total), np.float32)
    notes = sorted(spec['notes'], key=lambda n: n[0])
    mono = spec['role'] in MONO_ROLES
    fade = int(0.006 * SR)
    synced = spec['inst'] in synth.TEMPO_SYNCED
    for i, (st, dur, midi, vel, p) in enumerate(notes):
        if synced:
            p = dict(p, spb=round(spec['beat'], 4))
        x = synth.play(spec['inst'], midi, dur, vel, p)
        s0 = int(st * SR)
        if s0 >= n_total:
            continue
        if mono and i + 1 < len(notes):       # a new bass note cuts the one before (mono synth), with a short fade
            cut = int(notes[i + 1][0] * SR) - s0
            if 0 < cut < x.shape[1]:
                x = x[:, :cut + fade].copy()
                x[:, cut:] *= np.linspace(1, 0, x.shape[1] - cut, dtype=np.float32)
        e = min(n_total, s0 + x.shape[1])
        buf[:, s0:e] += x[:, :e - s0]
    role = spec['role']
    # tidy the low end: only kick, bass, riff and fx keep their sub
    if role not in ('kick', 'bass', 'riff', 'fx'):
        hpf = {'pad': 220, 'chords': 160, 'lead': 180, 'arp': 200, 'answer': 220, 'hat': 3000, 'ohat': 3000, 'ride': 2500, 'shaker': 4000,
               'snare': 110, 'clap': 200, 'perc': 90, 'rim': 300, 'cowbell': 300}.get(role, 120)
        buf = signal.sosfilt(signal.butter(2, hpf / (SR / 2), 'high', output='sos'), buf, axis=1).astype(np.float32)
    # the part's effects chain (drive, chorus, gate, OTT, echo ...)
    if spec.get('fx'):
        from .fx import apply_chain
        buf = apply_chain(buf, spec['fx'], spec['beat'], spec.get('secs'))
    # filter sweeps (automation)
    if spec.get('auto'):
        buf = apply_sweeps(buf, spec['auto'])
    # auto-gain to the role's target level
    measured = _krms_db(buf)
    gain_db = 0.0 if measured < -100 else float(np.clip(ROLE_TARGET.get(role, -22) + spec['level'] - measured, -36, 24))
    buf *= np.float32(10 ** (gain_db / 20))
    # width (Haas on the side) and pan
    if spec['width'] > 0:
        d = int(0.006 * spec['width'] * SR)
        side = (buf[0] - buf[1]) / 2
        mid = (buf[0] + buf[1]) / 2
        delayed = np.concatenate([np.zeros(d, np.float32), mid[:-d]])
        buf = np.vstack([mid + side + 0.3 * spec['width'] * (mid - delayed), mid - side - 0.3 * spec['width'] * (mid - delayed)])
    if spec['pan']:
        a = (spec['pan'] + 1) * np.pi / 4
        buf = np.vstack([buf[0] * np.cos(a) * 1.414, buf[1] * np.sin(a) * 1.414]).astype(np.float32)
    # sidechain: duck under each kick
    depth = spec['sc'] * spec['sc_depth']
    if depth > 0 and spec['kicks']:
        t = np.arange(n_total) / SR
        k = np.array(sorted(spec['kicks']))
        idx = np.searchsorted(k, t, side='right') - 1
        since = np.where(idx >= 0, t - k[np.clip(idx, 0, None)], 10.0)
        rel = spec['sc_release'] * spec['beat']
        att = np.clip(since / 0.004, 0, 1)
        env = 1 - depth * np.exp(-since / (rel / 3)) * att
        buf *= env.astype(np.float32)
    dry = buf
    wet = dry.copy()
    # delay: dotted 8th ping-pong, each repeat darker
    if spec['dly'] > 0:
        d = int(0.75 * spec['beat'] * SR)
        src = (dry[0] + dry[1]) * 0.5 * spec['dly']
        sos = signal.butter(1, 3500 / (SR / 2), 'low', output='sos')
        e = src
        for k in range(1, 6):
            e = signal.sosfilt(sos, e) * 0.5
            sh = d * k
            if sh >= n_total:
                break
            wet[k % 2, sh:] += e[:n_total - sh].astype(np.float32)
    # reverb send
    if spec['rev'] > 0:
        ir = impulse(spec['space'])
        src = (dry[0] + dry[1]) * 0.5 * spec['rev']
        src = signal.sosfilt(signal.butter(2, 250 / (SR / 2), 'high', output='sos'), src).astype(np.float32)
        wet += reverb(src, ir, n_total)
    return wet.astype(np.float32), dict(gain_db=round(gain_db, 1), level_db=round(measured, 1))


def apply_sweeps(buf, auto):
    """auto: {'lp' | 'hp': [[start_s, end_s, from_hz, to_hz], ...]} - exponential ramps; outside them the filter is off.
    Each ramp ends with a 15 ms crossfade back to the dry sound, so the filter lets go without a click."""
    n_total = buf.shape[1]
    fade = int(0.015 * SR)
    out = buf.copy()
    for kind, ramps in auto.items():
        for s0, s1, f0, f1 in ramps:
            a, b = int(s0 * SR), min(n_total, int(s1 * SR))
            if b - a < 256:
                continue
            e = min(n_total, b + fade)
            t = np.linspace(0.0, 1.0, b - a)
            cut = np.concatenate([f0 * (f1 / f0) ** t, np.full(e - b, f1)])
            for ch in range(out.shape[0]):
                seg = out[ch, a:e].astype(np.float64)
                y = synth.sweep(seg, cut, kind)
                if e > b:
                    r = np.linspace(0.0, 1.0, e - b)
                    y[b - a:] = y[b - a:] * (1 - r) + seg[b - a:] * r
                out[ch, a:e] = y.astype(np.float32)
    return out


def reverb(src, ir, n_out):
    """Stereo convolution reverb: one forward FFT of the send, one inverse per channel (float32)."""
    from scipy import fft as sfft
    N = sfft.next_fast_len(len(src) + ir.shape[1] - 1, real=True)
    X = sfft.rfft(src, N, workers=-1)
    out = np.empty((2, n_out), np.float32)
    for ch in range(2):
        out[ch] = sfft.irfft(X * sfft.rfft(ir[ch], N, workers=-1), N, workers=-1)[:n_out]
    return out


def _worker(args):
    spec, path = args
    x, info = render_track(spec)
    tmp = path + f'.{os.getpid()}.tmp.npy'
    np.save(tmp, x)
    with open(path[:-4] + '.json', 'w', encoding='utf-8') as f:
        json.dump(info, f)
    replace_file(tmp, path)
    return spec['id'], path, info


_POOL = None
_POOL_N = 0
_POOL_LOCK = threading.Lock()


def _pool(n):
    """One worker pool for the life of the app: starting worker processes costs a second or more each on Windows
    (they re-import numpy and scipy), so they are started once and reused for every render."""
    global _POOL, _POOL_N
    with _POOL_LOCK:
        if _POOL is None or _POOL_N < n:
            if _POOL is not None:
                _POOL.shutdown(wait=False, cancel_futures=True)
            _POOL = ProcessPoolExecutor(max_workers=n)
            _POOL_N = n
        return _POOL


def _reset_pool():
    global _POOL, _POOL_N
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL, _POOL_N = None, 0


atexit.register(_reset_pool)


def default_workers():
    """Worker processes: one per core, at most 61 (the Windows limit for a process pool)."""
    return max(1, min(61, os.cpu_count() or 2))


def replace_file(src, dst, tries=40):
    """os.replace that waits a moment when Windows reports the target as in use (a browser still reading the mix)."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.1)


def render_stems(song, cache_dir, progress=None, workers=None):
    """-> {track_id: stem path}. Only tracks whose spec changed are rendered."""
    os.makedirs(cache_dir, exist_ok=True)
    specs = track_specs(song)
    todo, paths, infos = [], {}, {}
    for s in specs:
        p = os.path.join(cache_dir, s['hash'] + '.npy')
        paths[s['id']] = p
        if os.path.exists(p):
            try:
                with open(p[:-4] + '.json', encoding='utf-8') as f:
                    infos[s['id']] = json.load(f)
            except Exception:
                infos[s['id']] = {}
        else:
            todo.append((s, p))
    done = len(specs) - len(todo)
    if progress:
        progress(done / max(1, len(specs)), f'{done} of {len(specs)} parts already rendered')
    if todo:
        workers = workers or default_workers()
        todo.sort(key=lambda a: -len(a[0]['notes']))

        def collect(it):
            nonlocal done
            for tid, p, info in it:
                done += 1
                infos[tid] = info
                if progress:
                    progress(done / len(specs), f'rendered {tid}')
        if workers == 1 or len(todo) == 1:
            collect(map(_worker, todo))
        else:
            try:
                collect(_pool(workers).map(_worker, todo))
            except BrokenProcessPool:                     # a worker died (out of memory, killed): start fresh once
                _reset_pool()
                todo = [a for a in todo if not os.path.exists(a[1])]
                collect(_pool(workers).map(_worker, todo))
    return paths, infos


# ------------------------------------------------------------------ master
def _peaking(f0, gain_db, q=1.0):
    A = 10 ** (gain_db / 40)
    w = 2 * np.pi * f0 / SR
    al = np.sin(w) / (2 * q)
    c = np.cos(w)
    b = np.array([1 + al * A, -2 * c, 1 - al * A])
    a = np.array([1 + al / A, -2 * c, 1 - al / A])
    return np.concatenate([b / a[0], a / a[0]])


def tone_of(x):
    """9-band tonal balance (dB, loudest band = 0) of a stereo signal."""
    m = x.mean(0)
    f, P = signal.welch(m, fs=SR, nperseg=8192)
    out = []
    for lo, hi in BANDS:
        idx = (f >= lo) & (f < hi)
        out.append(10 * np.log10(P[idx].sum() + 1e-15))
    out = np.array(out)
    return out - out.max()


def width_of(x):
    mid, side = (x[0] + x[1]) / 2, (x[0] - x[1]) / 2
    return float(np.sqrt((side ** 2).mean() / ((mid ** 2).mean() + 1e-12)))


MASTER_CHOICES = dict(loudness=['genre', 'club', 'stream'], width=['narrow', 'genre', 'wide'], tone=['darker', 'genre', 'brighter'],
                      glue=['off', 'genre', 'heavy'], tape=['off', 'on'])


def master(mix, g, brightness=0.0, opts=None):
    """Ref-steered master. -> (stereo float32, report dict)
    opts (the mixer's MASTER menu): loudness genre / club (-7 LUFS) / stream (-14), width narrow / genre / wide,
    tone darker / genre / brighter, glue off / genre / heavy, tape off / on."""
    fp = dict(g.get('fingerprint') or {})
    o = {k: v for k, v in (opts or {}).items() if k in MASTER_CHOICES and v in MASTER_CHOICES[k]}
    if o.get('width') in ('narrow', 'wide') and fp.get('width'):
        fp['width'] = fp['width'] * (0.6 if o['width'] == 'narrow' else 1.45)
    rep = {'options': o} if o else {}
    x = signal.sosfilt(signal.butter(2, 25 / (SR / 2), 'high', output='sos'), mix, axis=1)
    b = float(g.get('brightness', 0.0)) + brightness
    if b <= -0.6:                               # really dark genres (lo-fi): a gentle low-pass, like a worn tape
        fc = 2800 + 4000 * (1 + b)
        x = signal.sosfilt(signal.butter(2, fc / (SR / 2), 'low', output='sos'), x, axis=1)
        rep['tape_lowpass_hz'] = int(fc)
    # 1) tonal balance toward the references
    if fp.get('tone'):
        before = tone_of(x)
        target = np.array(fp['tone'], dtype=float)
        diff = target - before
        diff -= np.median(diff)
        diff = np.clip(diff, -6, 6) * 0.7
        diff = np.convolve(diff, [0.25, 0.5, 0.25], mode='same')
        sos = []
        for (lo, hi), gdb in zip(BANDS, diff):
            if abs(gdb) < 0.5:
                continue
            fc = np.sqrt(lo * hi)
            sos.append(_peaking(fc, gdb, q=0.9))
        if sos:
            x = signal.sosfilt(np.array(sos), x, axis=1)
        after = before + diff                     # predicted (saves a second spectrum pass)
        rep['tone_eq_db'] = [round(float(v), 1) for v in diff]
        rep['tone_error_before'] = round(float(np.abs(before - target).mean()), 1)
        rep['tone_error_after'] = round(float(np.abs(after - target).mean()), 1)
    # 2) stereo width and a mono low end
    mid, side = (x[0] + x[1]) / 2, (x[0] - x[1]) / 2
    if fp.get('low_side_db', 0) < -20 or fp.get('low_side_db') is None:
        side = signal.sosfilt(signal.butter(2, 120 / (SR / 2), 'high', output='sos'), side)
    if fp.get('width'):
        w = np.sqrt((side ** 2).mean() / ((mid ** 2).mean() + 1e-12))
        k = float(np.clip(fp['width'] / max(w, 1e-3), 0.5, 2.5))
        side = side * k
        rep['width_scale'] = round(k, 2)
    x = np.vstack([mid + side, mid - side])
    # tone tilt (MASTER menu)
    if o.get('tone') in ('darker', 'brighter'):
        sgn = 1 if o['tone'] == 'brighter' else -1
        x = signal.sosfilt(np.vstack([_shelf_sos(6500, 2.5 * sgn, 'high'), _shelf_sos(140, -1.0 * sgn, 'low')]), x, axis=1)
    # 3) glue compression (2:1 above -16 dB, 10 ms / 150 ms; heavy: 4:1 above -22 dB)
    if o.get('glue') != 'off':
        thr, ratio = (-22.0, 4.0) if o.get('glue') == 'heavy' else (-16.0, 2.0)
        env = np.abs(x).max(0)
        a_rel = np.exp(-1 / (0.15 * SR))
        lvl = signal.lfilter([1 - a_rel], [1, -a_rel], env)
        db = 20 * np.log10(lvl + 1e-9)
        gr = np.where(db > thr, (db - thr) * (1 - 1 / ratio), 0)
        x = x * (10 ** (-gr / 20))
        rep['glue_gr_db'] = round(float(np.percentile(gr, 95)), 1)
    if o.get('tape') == 'on':                       # tape saturation: rounds the peaks before the limiter
        pk = np.abs(x).max() + 1e-9
        y = np.tanh(x / pk * 1.8) / np.tanh(1.8) * pk
        x = signal.sosfilt(_shelf_sos(12000, -1.5, 'high'), y, axis=1)
    # 4) loudness to the genre's target, then a look-ahead limiter at -1 dBFS
    target_l = float(g.get('loudness', fp.get('lufs', -10)))
    if o.get('loudness') == 'club':
        target_l = max(target_l, -7.0)
    elif o.get('loudness') == 'stream':
        target_l = -14.0
    pre = x
    gain = target_l - lufs(pre, SR)
    x = limit(pre * 10 ** (gain / 20), -1.0)
    L1 = lufs(x, SR)
    if L1 < target_l - 0.5:                        # the limiter ate some loudness: push once more
        gain += min(4.0, target_l - L1)
        x = limit(pre * 10 ** (gain / 20), -1.0)
        L1 = lufs(x, SR)
    rep['lufs'] = round(L1, 1)
    rep['target_lufs'] = target_l
    rep['peak_db'] = round(float(20 * np.log10(np.abs(x).max() + 1e-9)), 1)
    rep['width'] = round(width_of(x), 2)
    rep['target_width'] = fp.get('width')
    return x.astype(np.float32), rep


def _shelf_sos(fc, gain_db, kind):
    from .fx import _sos
    return _sos('highshelf' if kind == 'high' else 'lowshelf', fc, 0.7, gain_db)[0]


def limit(x, ceiling_db=-1.0, look=0.0015):
    c = 10 ** (ceiling_db / 20)
    peak = np.abs(x).max(0)
    g = np.minimum(1.0, c / np.maximum(peak, 1e-9))
    w = max(3, int(look * SR))
    g = minimum_filter1d(g, size=2 * w + 1)
    g = uniform_filter1d(g, size=w)
    y = x * g
    return np.clip(y, -c, c)


# ------------------------------------------------------------------ mixing
def mix_stems(paths, song, mix=None):
    """Sum the stems with the user's mixer settings. mix: {track_id: {gain_db, pan, mute, solo}}"""
    mix = mix or {}
    solo = [t for t, m in mix.items() if m.get('solo')]
    acc = None
    for t in song.tracks:
        m = mix.get(t.id, {})
        if m.get('mute') or (solo and t.id not in solo) or t.id not in paths:
            continue
        x = np.load(paths[t.id])          # read whole: a memory map keeps the file locked on Windows
        g = 10 ** (float(m.get('gain_db', 0)) / 20)
        pan = float(m.get('pan', 0))
        if pan:
            l, r = (min(1, 1 - pan), min(1, 1 + pan))
            y = np.vstack([x[0] * g * l, x[1] * g * r])
        else:
            y = x * g
        acc = y.astype(np.float32) if acc is None else acc + y
    if acc is None:
        n = int((song.total_bars() * 4 * 60 / song.bpm + 4) * SR)
        acc = np.zeros((2, n), np.float32)
    # trim the silent tail (keep reverb ring-out)
    end = int(song.total_bars() * 4 * 60 / song.bpm * SR)
    tail = acc[:, end:]
    nz = np.nonzero(np.abs(tail).max(0) > 1e-4)[0]
    cut = end + (nz[-1] + int(0.2 * SR) if len(nz) else 0)
    return acc[:, :min(cut, acc.shape[1])]


def write_wav(path, x, sr=SR):
    rng = np.random.default_rng(0)
    d = (rng.random(x.shape) - rng.random(x.shape)) / 32768
    y = np.clip(x + d, -1, 1)
    pcm = (y.T * 32767).astype('<i2')
    tmp = path + '.tmp'
    with wave.open(tmp, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    replace_file(tmp, path)


def peaks(x, n=1600):
    m = np.abs(x).max(0)
    k = max(1, len(m) // n)
    m = m[:k * (len(m) // k)].reshape(-1, k).max(1)
    return np.round(m / (m.max() + 1e-9), 3).tolist()


def section_levels(x, song):
    bs = 60 / song.bpm
    out = []
    for s in song.sections:
        a, b = int(s.start_bar * 4 * bs * SR), int((s.start_bar + s.bars) * 4 * bs * SR)
        seg = x[:, a:b]
        out.append(round(float(10 * np.log10((seg ** 2).mean() + 1e-12)), 1) if seg.size else -99)
    return out
