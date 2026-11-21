# SL2

**Studio Lab 2: a local music generator with a classic media-player skin.**

Describe a track ("dark deep dubstep in F minor, long") or drop in a reference song, and SL2 composes, arranges, renders,
mixes and masters a full instrumental. Everything runs on your machine. No samples or AI services are needed: every sound is
synthesized.

It's a new app, not an update of Studio Lab. The engine, composer and genre system were rebuilt from scratch so that genres
stay distinct and each one is grounded in real reference tracks.

## Run it

### Windows

Download `SL2-Setup-<version>.exe` from the [latest release](https://github.com/kefirman9000/SL2/releases/latest) and
double-click it. Python, numpy and scipy are inside; nothing else to install, no admin password. If Windows shows
*"Windows protected your PC"*, click **More info → Run anyway** (the installer isn't signed with a paid certificate).
SL2 appears in the Start menu, opens in your browser, and saves songs in **Documents\SL2 Songs** (kept when you
update or uninstall). Prefer no installer? The release also has `SL2-<version>-Windows.zip`: unzip it anywhere and run
`SL2.exe`.

From the source code instead: install [Python 3.9+](https://www.python.org/downloads/) (tick *Add python.exe to
PATH*), download this repository and double-click **`Start SL2 (Windows).bat`**. The first start sets up a private
Python environment in `%LOCALAPPDATA%\SL2` (a minute or two); after that it opens straight away.

### Mac / Linux / any Python

```
pip install -r requirements.txt          # numpy + scipy (pytest for the tests)
python sl2.py                            # opens the app in your browser
python sl2.py make "sunny melodic deep house, long"    # or straight from the command line
```

Optional: [ffmpeg](https://ffmpeg.org/download.html) lets the reference analyser read MP3, FLAC, WMA and M4A (without it: WAV only).
Songs are saved in `songs/` (set `SL2_HOME` to put them elsewhere).

## The windows

| Window | What it does |
|---|---|
| **SL2** (player) | Green LCD with a spectrum visualizer and a scrolling title. BPM, key and genre readouts, volume and balance. Seek bar with section marks. ⏮ previous version (undo), ⏭ new take, ⏏ open a reference track, SHUFFLE (surprise genre), ↻ loop the current section. |
| **SL2 MIXER** | One fader per part, styled like a graphic EQ, plus a preamp fader. M / S / L = mute, solo, lock. Changes re-mix from cached stems (no re-rendering) in a few seconds. PRESETS: flat, drums up, low end up, melody up, chill. |
| **SL2 PLAYLIST** | Your songs. ADD composes a new one, REM deletes, SEL stars. MISC exports WAV, MP3 (with ffmpeg), stems (ZIP), MIDI or the song file, opens a song file, and copies diagnostics for a bug report. LIST OPTS shows the version history. |
| **SL2 COMPOSER** | Type a description or pick a genre (★ = modelled on reference tracks; search by name, sound or mood; ☆ your favourites; recent genres at the top). Set energy, length (short, normal, long, club or a 16-bar loop), BPM, key and seed. **Feel**: drum fills, hi-hats, ghost notes, build-ups, transition FX and how restless the song is. Drop a reference track to measure it and pick the closest genre, or drop a song file to open it. Your picks are remembered. |
| **SL2 EDITOR** | Section timeline: click to play from a section; **right-click** for section tools - loop it, a new take of just that section, duplicate, 4 bars longer / shorter, move earlier / later, remove, take a part out of it. Pick a part, change its sound, lock it, or re-roll only that part. **MORE LIKE THIS** makes a new song keeping what you tick (tempo & key, form, groove, bass, chords, melody, sounds); **SOMETHING DIFFERENT** changes everything but the genre. NEW CHORDS / NEW FORM / NEW TAKE keep locked parts. Piano roll: click to add or remove notes, then APPLY EDITS (the part is locked afterwards). |
| **SL2 INFO** | What the critic and the meters found: hook score, chords, how close the master got to the genre's references, section contrast, auto-gain. |

Double-click a title bar (or press ▁) to shade a window. **A/B** in the player compares two songs at the same spot.
Keys: space play/pause · ←/→ 5 s · [ ] previous / next section · L loop section · N new take · M more like this · B A/B · Z undo.

## What's smarter than Studio Lab 1

- **Every choice has its own seed** (seed × genre × part). The same seed never puts two genres in the same key, and
  re-rolling the melody leaves the drums, bass and chords exactly as they were.
- **Hooks are written and judged.** 48 candidate melodies are built from a motif (statement, sequence, answer, cadence) and
  scored on chord tones on strong beats, stepwise motion, leap recovery, range, a late climax and a stable ending. The best
  one wins, and the verse and breakdown lines are variations of it.
- **Chords move smoothly.** Each chord takes the voicing that moves least from the one before.
- **Locks work with re-rolls.** Lock the lead and ask for NEW CHORDS: the new progression is chosen to fit your locked melody.
- **Genres don't blend into each other.** Every genre pack has its own drums, sounds, song forms, bass style and mix targets, and a
  test fails if two genres share most of them.
- **Referenced genres.** Liquid DnB, Sunlit Electronica, Deep Dubstep, Melodic Deep House, Trance, Hard Electro, Tech House,
  Hard Trap, Memphis Phonk, Lo-fi Hip Hop and Spooky Surf were measured from real tracks (see [docs/REFERENCES.md](docs/REFERENCES.md)).
  The master steers each song toward its genre's tonal balance, stereo width, low-end mono and loudness.
- **Auto-gain.** Every part is measured and set to its role's level before you touch a fader.
- **Fast.** Parts render in parallel, one process per core, and are cached by content. Changing one sound re-renders one part,
  and mixer moves re-use every stem and only re-run the master (a few seconds). On 2 cores, about 1.5 minutes of music renders in 5–25 seconds, depending on the genre.
- **Versions.** Every change is a new version with a parent, so ⏮ is undo.

## What's new in 2.1: songs that move

- **Phrases, not loops.** The 4th, 8th and 16th bars of a phrase change: small fills, hats that drop out or open, a
  skipped kick, ghost snares. Hats and snares now vary 2-4x more from bar to bar than in 2.0.
- **Parts enter and leave** on the 8-bar grid in intros and outros; one part joins half-way through the first groove.
- **Filter sweeps** (automation, saved in the song): intros open up, builds thin out from the bottom, breakdowns bloom.
- **Later drops change**: the lead doubles an octave up or an extra layer joins, and trance, synthwave and liquid DnB
  can lift the key for the final drop.
- **Call and response**: in deep house, trance, synthwave, liquid DnB, sunlit and garage a second sound answers the
  lead in the gaps it leaves. The **trance breakdown** now states the theme on a piano.
- **Better hooks**: the critic now rewards leaning notes that resolve, an open half-way point and a closed ending,
  some syncopation, and penalises lines that only spell out the chords - so the best of 48 candidates is clearly
  better than a typical one. House gets chopped stabs, techno a hypnotic sequence.
- **Harmony**: a major V in minor keys (the leading tone pulls home), a borrowed minor iv in major keys, chords that
  arrive an 8th early, bass lines that walk into the next chord, one colour per chord for the whole song, and no
  more semitone clusters in voicings.
- **Fixes**: the breakdown melody followed the wrong chords; leads went silent at the end of some sections.
- **3-5 song forms per genre** instead of one or two.

## Genres

Classic House · Techno · Acid House · Tech House★ · Melodic Techno · Trance★ · Hard Electro★ · UK Garage ·
Liquid DnB★ · Neuro DnB · Deep Dubstep★ · Hard Trap★ · Memphis Phonk★ · Melodic Deep House★ · Sunlit Electronica★ ·
Lo-fi Hip Hop★ · Synthwave · Ambient · Spooky Surf★

A genre is one JSON file in `sl2/genres/`: tempo range, scales, chord moves, song forms, drum patterns per energy level, bass
style, lead rhythms, tracks with their sounds and send levels, and the reference fingerprint.

## Layout

```
sl2.py              start the app / `make` from the command line
sl2/compose.py      the composer (form, harmony, drums, bass, chords, arps, riffs, fx, variation, sweeps)
sl2/melody.py       motif-based hooks + the melody critic, chops, sequences, call and response
sl2/edit.py         section editing (duplicate, remove, move, resize, mute a part) on the song document
sl2/theory.py       keys, scales, chords, voice leading, per-part seeds
sl2/synth.py        every instrument and drum, synthesized with numpy
sl2/render.py       parallel cached stems, auto-gain, sidechain, sends, ref-steered master
sl2/analyze.py      reference analysis (tempo, key, drums, sections, tone, loudness, width, pump)
sl2/prompt.py       text description -> settings
sl2/store.py        songs, versions, jobs, exports
sl2/server.py       local HTTP server + API
sl2/ui/             the skin (index.html, skin.css, app.js, fonts)
sl2/cli.py          command line / app entry point
packaging/windows/  Windows app (PyInstaller) and installer (Inno Setup); built by .github/workflows/windows.yml
sl2/genres/         genre packs
tools/analyze_refs.py   measure reference tracks into numbers
```

## Tests

```
python -m pytest -q tests
```

`tests/test_music.py` checks the music itself: the lead fits the chords in every section, no section ends in silence,
no semitone clusters in chords, bars actually change, later drops differ, the critic separates good hooks from typical
ones, and section edits keep every note.

To build the Windows app yourself (on Windows): `pip install pyinstaller` then
`pyinstaller packaging/windows/sl2.spec --noconfirm` (and `iscc packaging\windows\sl2.iss` for the installer).

## License

MIT. Fonts: Space Grotesk and VT323, both under the SIL Open Font License (`sl2/ui/fonts/`). The skin is an original design
inspired by classic late-90s media players. It isn't affiliated with or based on any product's artwork, names or logos.
