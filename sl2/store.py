"""Songs on disk, versions, and background jobs.

songs/<id>/song.json   the song document
songs/<id>/meta.json   title, genre, parent version, report, mixer settings
songs/<id>/mix.wav     the mastered mix
songs/.stems/          rendered stems, shared by every version (keyed by what shapes them)

Every change that alters notes or sounds makes a new version whose parent is the old one, so undo is just
"open the parent". Mixer moves stay on the same version.
"""
import io
import json
import os
import shutil
import threading
import time
import traceback
import uuid
import zipfile

import numpy as np

from . import genres as G
from . import render as R
from .compose import compose, song_beats_notes
from .midi import write_midi
from .song import Clip, Note, Placement, Song

HOME = os.environ.get('SL2_HOME') or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'songs')
STEMS = os.path.join(HOME, '.stems')
JOBS = {}
_LOCK = threading.Lock()


def _dir(sid):
    if not sid or '/' in sid or '\\' in sid or sid.startswith('.'):
        raise ValueError('bad song id')
    return os.path.join(HOME, sid)


def load_song(sid):
    with open(os.path.join(_dir(sid), 'song.json'), encoding='utf-8') as f:
        return Song.from_json(f.read())


def load_meta(sid):
    with open(os.path.join(_dir(sid), 'meta.json'), encoding='utf-8') as f:
        return json.load(f)


def save_meta(sid, meta):
    p = os.path.join(_dir(sid), 'meta.json')
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=1)
    os.replace(p + '.tmp', p)


def _new_id(song):
    slug = ''.join(c if c.isalnum() else '-' for c in song.title.lower()).strip('-')[:24]
    return time.strftime('%Y%m%d-%H%M%S') + '-' + slug + '-' + uuid.uuid4().hex[:4]


# ------------------------------------------------------------------ jobs
def start_job(kind, fn, *args):
    jid = uuid.uuid4().hex[:10]
    JOBS[jid] = dict(id=jid, kind=kind, status='running', progress=0.0, message='starting', result=None, error=None, started=time.time())

    def progress(p, msg):
        JOBS[jid].update(progress=round(float(p), 3), message=msg)

    def run():
        try:
            with _LOCK:                    # one render at a time: they already use every core
                res = fn(*args, progress=progress)
            JOBS[jid].update(status='done', progress=1.0, result=res, message='done')
        except Exception as e:
            JOBS[jid].update(status='error', error=f'{type(e).__name__}: {e}', trace=traceback.format_exc()[-2000:])
    threading.Thread(target=run, daemon=True).start()
    return jid


# ------------------------------------------------------------------ making songs
def _finish(song, parent=None, mix=None, progress=None, note=''):
    """Save a song document as a new version, render it and master it. -> meta"""
    sid = _new_id(song)
    d = _dir(sid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'song.json'), 'w', encoding='utf-8') as f:
        f.write(song.to_json())
    meta = dict(id=sid, title=song.title, genre=song.genre, genre_name=G.load(song.genre)['name'], key=song.key, bpm=song.bpm,
                parent=parent, created=time.time(), note=note, mix=mix or {}, report=song.settings.get('report', {}))
    save_meta(sid, meta)
    return _mixdown(sid, song, meta, progress)


def _mixdown(sid, song, meta, progress=None):
    def prog(p, msg):
        if progress:
            progress(0.05 + 0.8 * p, msg)
    paths, infos = R.render_stems(song, STEMS, progress=prog)
    if progress:
        progress(0.88, 'mixing and mastering')
    mx = R.mix_stems(paths, song, meta.get('mix'))
    g = G.load(song.genre)
    m, rep = R.master(mx, g, float(song.settings.get('brightness') or 0))
    R.write_wav(os.path.join(_dir(sid), 'mix.wav'), m)
    meta['master'] = rep
    meta['autogain'] = infos
    meta['duration'] = round(m.shape[1] / R.SR, 2)
    meta['peaks'] = R.peaks(m)
    meta['section_db'] = R.section_levels(m, song)
    meta['insights'] = insights(song, meta)
    meta['rev'] = meta.get('rev', 0) + 1
    save_meta(sid, meta)
    if progress:
        progress(1.0, 'done')
    return meta


def generate(settings, progress=None):
    if progress:
        progress(0.02, 'writing the song')
    song = compose(settings)
    _apply_overrides(song, settings)
    return _finish(song, progress=progress, note='new song')


def _apply_overrides(song, settings):
    for tid, inst in (settings.get('instruments') or {}).items():
        for t in song.tracks:
            if t.id == tid:
                t.instrument = inst


def reroll(sid, what, progress=None):
    """Re-write one part ('harmony', 'drums', 'all' or a track id), keeping locked tracks note for note."""
    old = load_song(sid)
    meta = load_meta(sid)
    s = dict(old.settings)
    ps = dict(s.get('part_seeds') or {})
    if what == 'all':
        s['seed'] = int(s.get('seed', 1)) + 1
        ps = {}
    elif what == 'harmony':
        ps['harmony'] = ps.get('harmony', 0) + 1
        ps['voicing'] = ps.get('voicing', 0) + 1
    elif what == 'form':
        ps['form'] = ps.get('form', 0) + 1
    else:
        t = next((t for t in old.tracks if t.id == what), None)
        if t is None:
            raise ValueError(f'no track {what!r}')
        part = 'melody' if t.role == 'lead' else 'track-' + what
        ps[part] = ps.get(part, 0) + 1
    s['part_seeds'] = ps
    s.pop('report', None)
    locked = {t.id: song_beats_notes(old, t.id) for t in old.tracks if t.locked and t.id != what}
    keep_h = old.settings.get('harmony') if what not in ('harmony', 'all') else None
    if what == 'form':
        locked = {}
    song = compose(s, locked=locked, prev_harmony=keep_h)
    _apply_overrides(song, s)
    for t in song.tracks:                       # instrument / lock choices survive a re-roll
        o = next((x for x in old.tracks if x.id == t.id), None)
        if o:
            t.instrument = o.instrument
            t.locked = o.locked
    return _finish(song, parent=sid, mix=meta.get('mix'), progress=progress, note=f're-rolled {what}')


def set_lock(sid, tid, on):
    song = load_song(sid)
    for t in song.tracks:
        if t.id == tid:
            t.locked = bool(on)
    with open(os.path.join(_dir(sid), 'song.json'), 'w', encoding='utf-8') as f:
        f.write(song.to_json())
    return dict(ok=True)


def set_instrument(sid, tid, inst, progress=None):
    from .synth import known
    if not known(inst):
        raise ValueError(f'unknown sound {inst!r}')
    song = load_song(sid)
    meta = load_meta(sid)
    for t in song.tracks:
        if t.id == tid:
            t.instrument = inst
    song.settings.setdefault('instruments', {})[tid] = inst
    return _finish(song, parent=sid, mix=meta.get('mix'), progress=progress, note=f'{tid} sound -> {inst}')


def edit_notes(sid, tid, notes, progress=None):
    """Replace a track's notes (song beats). The track is locked afterwards, so re-rolls keep your edit."""
    song = load_song(sid)
    meta = load_meta(sid)
    t = song.track(tid)
    for p in t.placements:
        song.clips.pop(p.clip, None)
    t.placements = []
    by_sec = {}
    for n in notes:
        b, ln, m, v = float(n[0]), float(n[1]), float(n[2]), float(n[3]) if len(n) > 3 else 0.8
        si = next((i for i, x in enumerate(song.sections) if x.start_bar * 4 <= b < (x.start_bar + x.bars) * 4), None)
        if si is None:
            continue
        by_sec.setdefault(si, []).append(Note(round(b - song.sections[si].start_bar * 4, 4), max(0.03, ln), int(round(m)), max(0.05, min(1, v))))
    for si, ns in sorted(by_sec.items()):
        cid = f'{tid}@{si}~e{int(time.time())}'
        song.clips[cid] = Clip(cid, song.sections[si].bars * 4, sorted(ns, key=lambda n: n.beat))
        t.placements.append(Placement(cid, si))
    t.locked = True
    return _finish(song, parent=sid, mix=meta.get('mix'), progress=progress, note=f'edited {tid}')


def remix(sid, mix, progress=None):
    song = load_song(sid)
    meta = load_meta(sid)
    meta['mix'] = mix
    return _mixdown(sid, song, meta, progress)


# ------------------------------------------------------------------ reading
def song_view(sid):
    song = load_song(sid)
    meta = load_meta(sid)
    g = G.load(song.genre)
    from .synth import LABELS, ROLE_CHOICES
    tracks = []
    for t in song.tracks:
        notes = song.notes_of(t.id)
        tracks.append(dict(id=t.id, role=t.role, instrument=t.instrument, label=LABELS.get(t.instrument, t.instrument),
                           locked=t.locked, notes=len(notes), choices=[dict(id=c, label=LABELS.get(c, c)) for c in ROLE_CHOICES.get(t.role, [])],
                           mix=meta.get('mix', {}).get(t.id, {})))
    return dict(meta=meta, song=dict(title=song.title, genre=song.genre, genre_name=g['name'], key=song.key, bpm=song.bpm,
                                     bars=song.total_bars(), sections=[dict(name=s.name, start_bar=s.start_bar, bars=s.bars, kind=s.tags[0],
                                                                            energy=float(s.tags[1][1:])) for s in song.sections],
                                     settings={k: v for k, v in song.settings.items() if k not in ('report',)}),
                tracks=tracks)


def track_notes(sid, tid):
    song = load_song(sid)
    return [[round(n.beat, 4), round(n.length, 4), n.pitch, round(n.velocity, 3)] for n in song.notes_of(tid)]


def library(limit=200):
    if not os.path.isdir(HOME):
        return []
    out = []
    for d in sorted(os.listdir(HOME), reverse=True):
        if d.startswith('.'):
            continue
        try:
            m = load_meta(d)
            out.append({k: m.get(k) for k in ('id', 'title', 'genre', 'genre_name', 'key', 'bpm', 'parent', 'created', 'note', 'duration', 'starred')})
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def history(sid):
    chain = []
    cur = sid
    while cur and len(chain) < 100:
        try:
            m = load_meta(cur)
        except Exception:
            break
        chain.append(dict(id=m['id'], note=m.get('note', ''), created=m.get('created')))
        cur = m.get('parent')
    return chain


def delete(sid):
    shutil.rmtree(_dir(sid), ignore_errors=True)
    return dict(ok=True)


def star(sid, on):
    m = load_meta(sid)
    m['starred'] = bool(on)
    save_meta(sid, m)
    return dict(ok=True)


# ------------------------------------------------------------------ exports
def export_midi(sid):
    song = load_song(sid)
    p = os.path.join(_dir(sid), 'song.mid')
    write_midi(song, p)
    return p


def export_stems_zip(sid):
    song = load_song(sid)
    paths, _ = R.render_stems(song, STEMS)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for t in song.tracks:
            x = np.load(paths[t.id])
            pk = np.abs(x).max()
            if pk > 0.99:
                x = x / pk * 0.99
            tmp = os.path.join(_dir(sid), f'_stem_{t.id}.wav')
            R.write_wav(tmp, x)
            z.write(tmp, f'{t.id}.wav')
            os.remove(tmp)
    return buf.getvalue()


# ------------------------------------------------------------------ insights
def insights(song, meta):
    """Plain-language notes about the finished song (what the critic and the meters found)."""
    out = []
    rep = meta.get('report', {})
    mel = rep.get('melody') or {}
    if mel:
        out.append(f"Hook: best of {mel.get('candidates')} candidates (score {mel.get('score')}). "
                   f"{int(100 * mel.get('chord_tones', 0))}% chord tones on strong beats, {int(100 * mel.get('steps', 0))}% stepwise, "
                   f"range {mel.get('range')} scale steps.")
    out.append(f"Chords: {rep.get('progression', '?')}" + (f"; breakdown: {rep['break_progression']}" if rep.get('break_progression') else ''))
    ms = meta.get('master') or {}
    if ms.get('tone_error_before') is not None:
        out.append(f"Master steered toward the {meta.get('genre_name')} references: tone error {ms['tone_error_before']} → {ms['tone_error_after']} dB, "
                   f"width {ms.get('width')} (target {ms.get('target_width')}), {ms.get('lufs')} LUFS (target {ms.get('target_lufs')}).")
    sdb = meta.get('section_db') or []
    if sdb:
        kinds = [s.tags[0] for s in song.sections]
        drops = [v for v, k in zip(sdb, kinds) if k == 'drop']
        quiet = [v for v, k in zip(sdb, kinds) if k in ('break', 'intro')]
        if drops and quiet:
            c = max(drops) - min(quiet)
            out.append(f'Section contrast: {c:.1f} dB between the loudest drop and the quietest break/intro.'
                       + (' That is small - lower the energy or re-roll the form for a deeper breakdown.' if c < 3 else ''))
    return out
