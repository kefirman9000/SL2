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
from scipy.ndimage import maximum_filter1d, minimum_filter1d, uniform_filter1d

from . import genres as G
from . import synth
from .analyze import BANDS, lufs

SR = synth.SR
ENGINE = 'sl2-engine-2'                     # 2: round-robin drums, tuned kicks, ducked and section-shaped sends
SEND_BY_KIND = {'drop': 0.8, 'groove': 1.0, 'build': 1.15, 'break': 1.45, 'intro': 1.2, 'outro': 1.35}
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


@functools.lru_cache(maxsize=64)
def kick_f0(inst):
    """The fundamental of a kick sound (Hz), measured from its tail."""
    x = np.asarray(synth.play(inst, 36, 0.3, 1.0, {}), float).mean(0)
    a = int(0.04 * SR)
    seg = x[a:a + int(0.25 * SR)]
    if len(seg) < 2048:
        return 50.0
    F = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 1 << 16))
    f = np.fft.rfftfreq(1 << 16, 1 / SR)
    m = (f > 30) & (f < 130)
    return float(f[m][np.argmax(F[m])])


def kick_tune(inst, key_name):
    """Semitones that put a kick on the song's root (or its fifth when that's closer), at most 3 either way."""
    from .theory import parse_key
    pk = parse_key(key_name or '')
    if not pk:
        return 0.0
    cur = 12 * np.log2(kick_f0(inst) / 440.0) + 69
    best = None
    for target_pc in (pk[0], (pk[0] + 7) % 12):
        d = ((target_pc - cur) % 12 + 6) % 12 - 6
        if best is None or abs(d) < abs(best):
            best = d
    return float(np.clip(round(best, 2), -3, 3))


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
        if t.role == 'kick':
            spec['tune'] = kick_tune(t.instrument, song.key)
        if spec['rev'] > 0 or spec['dly'] > 0:            # sends follow the arrangement: tight drops, wet breakdowns,
            curve, throws = [], []                         # and a delay throw on the last beat before each drop
            for i, x in enumerate(song.sections):
                s0, s1 = round(x.start_bar * 4 * bs, 5), round((x.start_bar + x.bars) * 4 * bs, 5)
                curve.append([s0, s1, SEND_BY_KIND.get(x.tags[0], 1.0)])
                if i + 1 < len(song.sections) and song.sections[i + 1].tags[0] == 'drop' and t.role in ('lead', 'answer', 'chords', 'arp'):
                    throws.append([round(s1 - bs, 5), s1])
            spec['sends'] = curve
            if throws:
                spec['throws'] = throws
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
    role = spec['role']
    drum = role in DRUMS
    tune = spec.get('tune', 0.0)
    for i, (st, dur, midi, vel, p) in enumerate(notes):
        if synced:
            p = dict(p, spb=round(spec['beat'], 4))
        if drum:                                   # 4 round-robin takes, so no two hits in a row are identical
            p = dict(p, rr=i % 4)
            if tune:
                p['tune'] = tune
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
    sends = np.zeros_like(dry)
    mono_dry = (dry[0] + dry[1]) * 0.5
    curve = np.ones(n_total, np.float32)
    for s0, s1, m in spec.get('sends', []):
        curve[int(s0 * SR):int(s1 * SR)] = m
    curve = uniform_filter1d(curve, int(0.25 * SR)).astype(np.float32)
    throw = np.zeros(n_total, np.float32)
    for s0, s1 in spec.get('throws', []):
        throw[int(s0 * SR):int(s1 * SR)] = 1.0
    # delay: dotted 8th ping-pong, each repeat darker (+ throws into the drops)
    if spec['dly'] > 0 or spec.get('throws'):
        d = int(0.75 * spec['beat'] * SR)
        src = mono_dry * (spec['dly'] * curve + 0.6 * throw)
        sos = signal.butter(1, 3500 / (SR / 2), 'low', output='sos')
        e = src
        for k in range(1, 6):
            e = signal.sosfilt(sos, e) * 0.5
            sh = d * k
            if sh >= n_total:
                break
            sends[k % 2, sh:] += e[:n_total - sh].astype(np.float32)
    # reverb send, with a tempo-synced pre-delay (a 1/32 note, at most 60 ms) so the dry hit stays in front
    if spec['rev'] > 0:
        ir = impulse(spec['space'])
        pre = int(min(0.06, spec['beat'] / 8) * SR)
        src = mono_dry * spec['rev'] * curve
        src = signal.sosfilt(signal.butter(2, 250 / (SR / 2), 'high', output='sos'), src).astype(np.float32)
        src = np.concatenate([np.zeros(pre, np.float32), src[:n_total - pre]])
        sends += reverb(src, ir, n_total)
    if spec['rev'] > 0 or spec['dly'] > 0:
        # ducked sends: the echoes and the room step back while the part plays and bloom in its gaps
        env = np.sqrt(np.maximum(uniform_filter1d(mono_dry.astype(np.float64) ** 2, int(0.03 * SR)), 0))
        ref = np.percentile(env[env > 1e-5], 90) if (env > 1e-5).any() else 1.0
        duck = 1 - 0.5 * np.clip(env / (ref + 1e-9), 0, 1)
        duck = uniform_filter1d(duck, int(0.12 * SR)).astype(np.float32)
        sends *= duck
    wet = dry + sends
    return wet.astype(np.float32), dict(gain_db=round(gain_db, 1), level_db=round(measured, 1), tune=tune or None)


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
                      glue=['off', 'genre', 'heavy'], tape=['off', 'on'], buses=['on', 'off'])


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
    # 4) loudness to the genre's target: a soft clipper takes the tops off the loudest transients, then a look-ahead
    #    true-peak limiter holds -1 dBTP
    target_l = float(g.get('loudness', fp.get('lufs', -10)))
    if o.get('loudness') == 'club':
        target_l = max(target_l, -7.0)
    elif o.get('loudness') == 'stream':
        target_l = -14.0
    pre = x
    gain = target_l - lufs(pre, SR)
    x = limit(soft_clip(pre * 10 ** (gain / 20), -1.0), -1.0)
    L1 = lufs(x, SR)
    if L1 < target_l - 0.5:                        # the limiter ate some loudness: push once more
        gain += min(4.0, target_l - L1)
        x = limit(soft_clip(pre * 10 ** (gain / 20), -1.0), -1.0)
        L1 = lufs(x, SR)
    rep['lufs'] = round(L1, 1)
    rep['target_lufs'] = target_l
    rep['peak_db'] = round(float(20 * np.log10(np.abs(x).max() + 1e-9)), 1)
    rep['true_peak_db'] = round(float(20 * np.log10(true_peak(x).max() + 1e-9)), 1)
    rep['width'] = round(width_of(x), 2)
    rep['target_width'] = fp.get('width')
    return x.astype(np.float32), rep


def _shelf_sos(fc, gain_db, kind):
    from .fx import _sos
    return _sos('highshelf' if kind == 'high' else 'lowshelf', fc, 0.7, gain_db)[0]


def true_peak(x, os_=4):
    """Inter-sample (true) peak per sample of x, from a 4x oversampled copy: what a DAC or an MP3 decoder will see."""
    up = signal.resample_poly(x, os_, 1, axis=1)
    return np.abs(up).max(0).reshape(-1, os_).max(1)[:x.shape[1]] if up.shape[1] >= x.shape[1] * os_ else np.abs(x).max(0)


def soft_clip(x, ceiling_db=-1.0, knee_db=4.0):
    """Clip the very tops of the loudest transients smoothly before the limiter, so it has less to do (less pumping)."""
    c = 10 ** (ceiling_db / 20)
    t = c * 10 ** (-knee_db / 20)
    a = np.abs(x)
    over = a > t
    y = x.copy()
    y[over] = np.sign(x[over]) * (t + (c - t) * np.tanh((a[over] - t) / (c - t)))
    return y


def limit(x, ceiling_db=-1.0, look=0.0015):
    """Look-ahead limiter on the true (inter-sample) peak: nothing goes over the ceiling once decoded."""
    c = 10 ** (ceiling_db / 20)
    y = x
    for _ in range(3):
        peak = true_peak(y)
        if peak.max() <= c * 1.0005:
            break
        g = np.minimum(1.0, c / np.maximum(peak, 1e-9))
        w = max(3, int(look * SR))
        g = minimum_filter1d(g, size=2 * w + 1)
        g = uniform_filter1d(g, size=w)
        y = y * g
    return np.clip(y, -c, c)


# ------------------------------------------------------------------ mixing
BUS_OF = {**{r: 'drums' for r in DRUMS}, 'bass': 'low', 'riff': 'low', 'chords': 'music', 'pad': 'music', 'arp': 'music',
          'answer': 'music', 'lead': 'lead', 'fx': 'fx'}


def _comp_gain(x, thr_db, ratio, att, rel):
    """Gain curve (n,) of a feed-forward compressor on (2, n) x."""
    lvl = np.abs(x).max(0)
    env = maximum_filter1d(lvl, max(1, int(att * SR)))
    a = np.exp(-1 / max(1, rel * SR))
    env = signal.lfilter([1 - a], [1, -a], env)
    db = 20 * np.log10(env + 1e-9)
    gr = np.maximum(0, db - thr_db) * (1 - 1 / ratio)
    return 10 ** (-gr / 20)


def bus_process(buses, info):
    """The mix buses, the way an engineer would set them up:
    drums  parallel ('New York') compression under the dry kit + a touch of saturation: punch without losing transients
    low    the bass and riff below 120 Hz kept mono, plus their own upper harmonics so the bass reads on small speakers
    music  chords, pads and arps make room for the lead: a dynamic dip at the lead's own frequency while it plays
    -> one stereo mix"""
    out = None
    n = max(b.shape[1] for b in buses.values())

    def pad(x):
        return x if x.shape[1] == n else np.pad(x, ((0, 0), (0, n - x.shape[1])))
    buses = {k: pad(v.astype(np.float64)) for k, v in buses.items()}
    if 'drums' in buses:
        d = buses['drums']
        g = _comp_gain(d, -24.0, 6.0, 0.001, 0.08)
        crushed = d * g
        crushed *= np.sqrt((d ** 2).mean() / max((crushed ** 2).mean(), 1e-12))
        crushed = np.tanh(crushed * 1.6) / 1.6
        buses['drums'] = d + 0.28 * crushed
        info['drum_bus'] = 'parallel compression 28 %'
    if 'low' in buses:
        x = buses['low']
        sos_lo = signal.butter(4, 120 / (SR / 2), 'low', output='sos')
        lo = signal.sosfilt(sos_lo, x, axis=1)
        hi = x - lo
        mono_lo = lo.mean(0, keepdims=True).repeat(2, 0)
        harm = np.tanh(mono_lo * 4.0)
        harm = signal.sosfilt(signal.butter(2, [160 / (SR / 2), 1200 / (SR / 2)], 'band', output='sos'), harm, axis=1)
        k = 0.12 * np.sqrt((mono_lo ** 2).mean() / max((harm ** 2).mean(), 1e-12))
        buses['low'] = mono_lo + hi + harm * k
        info['low_bus'] = 'mono below 120 Hz, sub harmonics added'
    if 'lead' in buses and 'music' in buses:
        lead = buses['lead']
        f, P = signal.welch(lead.mean(0)[:SR * 120], SR, nperseg=8192)
        band = (f > 400) & (f < 5000)
        if P[band].sum() > 0:
            f0 = float(f[band][np.argmax(P[band])])
            from .fx import _sos
            cut = signal.sosfilt(_sos('peak', f0, 1.2, -3.0), buses['music'], axis=1)
            env = np.sqrt(np.maximum(uniform_filter1d(lead.mean(0) ** 2, int(0.05 * SR)), 0))
            ref = np.percentile(env[env > 1e-5], 80) if (env > 1e-5).any() else 1.0
            act = uniform_filter1d(np.clip(env / (ref + 1e-9), 0, 1), int(0.1 * SR))
            buses['music'] = buses['music'] + (cut - buses['music']) * act
            info['music_bus'] = f'-3 dB at {f0:.0f} Hz while the lead plays'
    for v in buses.values():
        out = v if out is None else out + v
    return out.astype(np.float32)


def mix_stems(paths, song, mix=None, info=None, buses_out=None):
    """Sum the stems with the user's mixer settings through the mix buses. mix: {track_id: {gain_db, pan, mute, solo}}"""
    mix = mix or {}
    info = info if info is not None else {}
    solo = [t for t, m in mix.items() if m.get('solo')]
    buses = {}
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
        b = BUS_OF.get(t.role, 'music')
        buses[b] = y.astype(np.float32) if b not in buses else _add(buses[b], y)
    if buses_out is not None:
        buses_out.update({k: v for k, v in buses.items() if k in ('lead', 'music')})
    if buses and (mix.get('_master') or {}).get('buses', 'on') != 'off':
        acc = bus_process(buses, info)
    elif buses:
        for v in buses.values():
            acc = v if acc is None else _add(acc, v)
    if acc is None:
        n = int((song.total_bars() * 4 * 60 / song.bpm + 4) * SR)
        acc = np.zeros((2, n), np.float32)
    # trim the silent tail (keep reverb ring-out)
    end = int(song.total_bars() * 4 * 60 / song.bpm * SR)
    tail = acc[:, end:]
    nz = np.nonzero(np.abs(tail).max(0) > 1e-4)[0]
    cut = end + (nz[-1] + int(0.2 * SR) if len(nz) else 0)
    return acc[:, :min(cut, acc.shape[1])]


def _add(a, b):
    n = max(a.shape[1], b.shape[1])
    out = np.zeros((2, n), np.float32)
    out[:, :a.shape[1]] += a
    out[:, :b.shape[1]] += b
    return out


def write_wav(path, x, sr=SR, bits=16):
    """16-bit with TPDF dither (the player, sharing), or 24-bit (for mastering elsewhere)."""
    rng = np.random.default_rng(0)
    q = 2 ** (bits - 1)
    d = (rng.random(x.shape) - rng.random(x.shape)) / q
    y = np.clip(x + d, -1, 1 - 1 / q)
    if bits == 24:
        v = np.round(y.T * (q - 1)).astype('<i4').reshape(-1)
        pcm = np.frombuffer(v.tobytes(), np.uint8).reshape(-1, 4)[:, :3].tobytes()
    else:
        pcm = (y.T * (q - 1)).astype('<i2').tobytes()
    tmp = path + '.tmp'
    with wave.open(tmp, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(bits // 8)
        w.setframerate(sr)
        w.writeframes(pcm)
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
