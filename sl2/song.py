"""The song document: the one source of truth for a song.

The composer writes notes into it, the editor changes it directly, and the sound engine and mixer only read it.
It saves to plain JSON, so a song can be reopened, diffed and edited without composing it again (in Studio Lab 1
an edit is stored as seeds plus patches and the whole song is re-composed to apply it).

    Song
      sections   the timeline: name, start bar, length
      tracks     one per sound: role, instrument / patch, mix settings, locked
        clips    notes placed in a section (a clip can be shared by several sections: edit once, change everywhere)
      automation per track, values over time in beats
"""
from dataclasses import asdict, dataclass, field
import json

FORMAT = 'studio-lab-2/song'
VERSION = 1


@dataclass
class Note:
    beat: float          # start, in beats from the clip's start
    length: float        # beats
    pitch: int           # MIDI note (a float is allowed for quarter tones)
    velocity: float = 0.8  # 0..1
    p: dict = field(default_factory=dict)   # sound parameters for this note (wobble rate, 808 glide, fx kind ...)


@dataclass
class Clip:
    id: str
    length_beats: float
    notes: list = field(default_factory=list)


@dataclass
class Placement:
    clip: str            # clip id
    section: int         # index into Song.sections
    offset_beats: float = 0.0


@dataclass
class Track:
    id: str
    role: str            # kick, snare, top, bass, chords, pad, arp, lead, fx, counter, vocal ...
    instrument: str      # built-in sound id or plugin patch id
    params: dict = field(default_factory=dict)
    gain_db: float = 0.0
    pan: float = 0.0
    sends: dict = field(default_factory=dict)        # bus -> level 0..1 (reverb, delay ...)
    muted: bool = False
    locked: bool = False                             # regenerate everything except this
    placements: list = field(default_factory=list)
    automation: dict = field(default_factory=dict)   # param -> [[beat, value], ...]


@dataclass
class Section:
    name: str            # intro, verse, build, drop ...
    start_bar: int
    bars: int
    tags: list = field(default_factory=list)         # build, drop, fade, alt ...


@dataclass
class Song:
    title: str
    genre: str
    seed: int
    bpm: float
    key: str             # 'Eb dorian'
    meter: list = field(default_factory=lambda: [4, 4])
    sections: list = field(default_factory=list)
    tracks: list = field(default_factory=list)
    clips: dict = field(default_factory=dict)        # id -> Clip
    settings: dict = field(default_factory=dict)     # what the user picked (so "regenerate" keeps it)

    # ---- queries
    def total_bars(self):
        return max((s.start_bar + s.bars for s in self.sections), default=0)

    def track(self, track_id):
        return next(t for t in self.tracks if t.id == track_id)

    def notes_of(self, track_id):
        """Every note the track plays, in song beats."""
        bpb = self.meter[0] * 4 / self.meter[1]
        out = []
        for p in self.track(track_id).placements:
            s0 = self.sections[p.section].start_bar * bpb + p.offset_beats
            for n in self.clips[p.clip].notes:
                out.append(Note(s0 + n.beat, n.length, n.pitch, n.velocity, dict(n.p)))
        return sorted(out, key=lambda n: (n.beat, n.pitch))

    # ---- save / load
    def to_json(self):
        d = asdict(self)
        d['clips'] = {k: asdict(v) if not isinstance(v, dict) else v for k, v in self.clips.items()}
        return json.dumps(dict(format=FORMAT, version=VERSION, song=d), indent=1)

    @classmethod
    def from_json(cls, text):
        doc = json.loads(text)
        if doc.get('format') != FORMAT:
            raise ValueError('not a Studio Lab 2 song')
        if doc.get('version', 0) > VERSION:
            raise ValueError(f'song was saved by a newer Studio Lab (format {doc["version"]})')
        d = doc['song']
        d['sections'] = [Section(**s) for s in d['sections']]
        d['clips'] = {k: Clip(id=c['id'], length_beats=c['length_beats'], notes=[Note(**n) for n in c['notes']])
                      for k, c in d['clips'].items()}
        tracks = []
        for t in d['tracks']:
            t['placements'] = [Placement(**p) for p in t['placements']]
            tracks.append(Track(**t))
        d['tracks'] = tracks
        return cls(**d)
