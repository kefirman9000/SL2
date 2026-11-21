import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sl2.song import Clip, Note, Placement, Section, Song, Track  # noqa: E402


def small_song():
    s = Song(title='Test', genre='house', seed=1, bpm=124, key='A minor')
    s.sections = [Section('intro', 0, 8), Section('drop', 8, 16, ['drop'])]
    s.clips['bass1'] = Clip('bass1', 4, [Note(0, 0.5, 33), Note(1.5, 0.5, 33, 0.6)])
    s.tracks = [Track('bass', 'bass', 'round_mono_bass',
                      placements=[Placement('bass1', 1), Placement('bass1', 1, 4)])]
    return s


def test_round_trip():
    s = small_song()
    again = Song.from_json(s.to_json())
    assert again == s


def test_shared_clip_and_song_beats():
    s = small_song()
    notes = s.notes_of('bass')
    assert [n.beat for n in notes] == [32, 33.5, 36, 37.5]     # drop starts at bar 8 = beat 32
    s.clips['bass1'].notes[0].pitch = 36                       # edit once ...
    assert [n.pitch for n in s.notes_of('bass')][::2] == [36, 36]   # ... changes every placement


def test_total_bars():
    assert small_song().total_bars() == 24
