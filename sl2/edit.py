"""Section editing on the song document: duplicate, remove, move, lengthen, shorten, mute a part in a section.

The notes stay exactly as they are (clips are moved, not re-composed). The edited layout is also written into the
song's settings (form_override, section_mutes) so a later re-roll of one part composes over the same layout.
"""
import copy
import uuid

from .song import Clip, Note, Placement

ACTIONS = ('duplicate', 'remove', 'left', 'right', 'longer', 'shorter', 'mute', 'unmute')


def _base_energy(sec):
    for t in sec.tags[1:]:
        if t.startswith('b'):
            return float(t[1:])
    return float(sec.tags[1][1:])


def segments(song):
    """The song as a list of self-contained sections: the section, each track's clips in it, its automation ramps
    (section-relative beats) and the parts muted in it."""
    mutes = {int(k): set(v) for k, v in (song.settings.get('section_mutes') or {}).items()}
    segs = []
    for si, sec in enumerate(song.sections):
        s0, s1 = sec.start_bar * 4, (sec.start_bar + sec.bars) * 4
        clips = {t.id: [p.clip for p in t.placements if p.section == si] for t in song.tracks}
        auto = {t.id: {k: [[a - s0, b - s0, f0, f1] for a, b, f0, f1 in v if s0 <= a < s1] for k, v in (t.automation or {}).items()}
                for t in song.tracks}
        segs.append(dict(sec=copy.deepcopy(sec), clips=clips, auto=auto, mutes=set(mutes.get(si, ()))))
    return segs


def rebuild(song, segs):
    bar = 0
    for t in song.tracks:
        t.placements = []
        t.automation = {}
    sections = []
    for i, sg in enumerate(segs):
        sec = sg['sec']
        sec.start_bar = bar
        sections.append(sec)
        for t in song.tracks:
            for cid in sg['clips'].get(t.id, []):
                t.placements.append(Placement(cid, i))
            for k, v in sg['auto'].get(t.id, {}).items():
                for a, b, f0, f1 in v:
                    t.automation.setdefault(k, []).append([a + bar * 4, b + bar * 4, f0, f1])
        bar += sec.bars
    song.sections = sections
    used = {p.clip for t in song.tracks for p in t.placements}
    song.clips = {k: v for k, v in song.clips.items() if k in used}
    song.settings['form_override'] = [[sg['sec'].name, sg['sec'].bars, _base_energy(sg['sec'])] for sg in segs]
    song.settings['section_mutes'] = {str(i): sorted(sg['mutes']) for i, sg in enumerate(segs) if sg['mutes']}


def _new_clip(song, tid, notes, length):
    cid = f'{tid}@x{uuid.uuid4().hex[:8]}'
    song.clips[cid] = Clip(cid, length, sorted(notes, key=lambda n: (n.beat, n.pitch)))
    return cid


def _resize_notes(notes, L, n):
    """Grow (n > 0) or shrink (n < 0) a clip of L beats by |n| beats, keeping its last bars (the fill into the next
    section) at the end: growing repeats the bars before them, shrinking takes bars out before them."""
    out = []
    if n > 0:
        src0, src1 = (L - 2 * n, L - n) if L >= 2 * n else (0, min(n, L))
        cut = L - n if L >= 2 * n else L
        for x in notes:
            if x.beat >= cut:
                out.append(Note(x.beat + n, x.length, x.pitch, x.velocity, dict(x.p)))
            else:
                out.append(copy.deepcopy(x))
            if src0 <= x.beat < src1:
                out.append(Note(x.beat - src0 + cut, min(x.length, src1 - x.beat), x.pitch, x.velocity, dict(x.p)))
    else:
        k = -n
        a, b = (L - 2 * k, L - k) if L >= 3 * k else (L - k, L)
        for x in notes:
            if a <= x.beat < b:
                continue
            if x.beat >= b:
                out.append(Note(x.beat - k, x.length, x.pitch, x.velocity, dict(x.p)))
            else:
                out.append(Note(x.beat, min(x.length, a - x.beat) if x.beat + x.length > a else x.length, x.pitch, x.velocity, dict(x.p)))
    newL = L + n
    return [x for x in out if x.beat < newL], newL


def apply(song, index, action, track=None, bars=4):
    """Edit one section in place. -> a short description of what changed."""
    segs = segments(song)
    if not 0 <= index < len(segs):
        raise ValueError('no such section')
    sg = segs[index]
    name = sg['sec'].name
    if action == 'duplicate':
        segs.insert(index + 1, dict(sec=copy.deepcopy(sg['sec']), clips={k: list(v) for k, v in sg['clips'].items()},
                                    auto=copy.deepcopy(sg['auto']), mutes=set(sg['mutes'])))
        what = f'duplicated {name}'
    elif action == 'remove':
        if len(segs) == 1:
            raise ValueError("can't remove the only section")
        segs.pop(index)
        what = f'removed {name}'
    elif action in ('left', 'right'):
        j = index - 1 if action == 'left' else index + 1
        if not 0 <= j < len(segs):
            raise ValueError('nothing to swap with')
        segs[index], segs[j] = segs[j], segs[index]
        what = f'moved {name} {action}'
    elif action in ('longer', 'shorter'):
        n = int(bars) * 4 * (1 if action == 'longer' else -1)
        L = sg['sec'].bars * 4
        if L + n < 4 * 4:
            raise ValueError('a section needs at least 4 bars')
        for tid, cids in sg['clips'].items():
            new = []
            for cid in cids:
                notes, newL = _resize_notes(song.clips[cid].notes, L, n)
                new.append(_new_clip(song, tid, notes, newL))
            sg['clips'][tid] = new
        k = (L + n) / L
        sg['auto'] = {tid: {p: [[a * k, b * k, f0, f1] for a, b, f0, f1 in v] for p, v in d.items()} for tid, d in sg['auto'].items()}
        sg['sec'].bars += n // 4
        what = f'{name} {"+" if n > 0 else "-"}{abs(n) // 4} bars'
    elif action in ('mute', 'unmute'):
        t = next((t for t in song.tracks if t.id == track), None)
        if t is None:
            raise ValueError(f'no track {track!r}')
        if action == 'mute':
            sg['mutes'].add(track)
            sg['clips'][track] = []
            what = f'{track} out of {name}'
        else:
            sg['mutes'].discard(track)
            what = f'{track} back in {name} (on the next re-roll of that part)'
    else:
        raise ValueError(f'unknown action {action!r}')
    rebuild(song, segs)
    return what


def take_section(song, other, index):
    """Copy every unlocked track's notes of one section from `other` (same layout) into `song`."""
    for t in song.tracks:
        if t.locked:
            continue
        o = next((x for x in other.tracks if x.id == t.id), None)
        t.placements = [p for p in t.placements if p.section != index]
        if o is None:
            continue
        for p in o.placements:
            if p.section == index:
                c = other.clips[p.clip]
                cid = _new_clip(song, t.id, [copy.deepcopy(n) for n in c.notes], c.length_beats)
                t.placements.append(Placement(cid, index))
        t.placements.sort(key=lambda p: p.section)
    used = {p.clip for t in song.tracks for p in t.placements}
    song.clips = {k: v for k, v in song.clips.items() if k in used}
