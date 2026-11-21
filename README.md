# SL2

**Studio Lab 2: a local music generator with a classic media-player skin.**

Describe a track ("dark deep dubstep in F minor, long") or drop in a reference song, and SL2 composes, arranges, renders,
mixes and masters a full instrumental. Everything runs on your machine. No samples or AI services are needed: every sound is
synthesized.

It's a new app, not an update of Studio Lab. The engine, composer and genre system were rebuilt from scratch so that genres
stay distinct and each one is grounded in real reference tracks.

## Run it

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
| **SL2 PLAYLIST** | Your songs. ADD composes a new one, REM deletes, SEL stars. MISC exports WAV, stems (ZIP), MIDI or the song file. LIST OPTS shows the version history. |
| **SL2 COMPOSER** | Type a description or pick a genre (★ = modelled on reference tracks). Set energy, length, BPM, key and seed. Drop a reference track to measure it and pick the closest genre. |
| **SL2 EDITOR** | Section timeline (click to jump). Pick a part, change its sound, lock it, or re-roll only that part. NEW CHORDS / NEW FORM / NEW TAKE keep locked parts. Piano roll: click to add or remove notes, then APPLY EDITS (the part is locked afterwards). |
| **SL2 INFO** | What the critic and the meters found: hook score, chords, how close the master got to the genre's references, section contrast, auto-gain. |

Double-click a title bar (or press ▁) to shade a window. Space bar = play/pause.

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

## Genres

Classic House · Techno · Acid House · Tech House★ · Melodic Techno · Trance★ · Hard Electro★ · UK Garage ·
Liquid DnB★ · Neuro DnB · Deep Dubstep★ · Hard Trap★ · Memphis Phonk★ · Melodic Deep House★ · Sunlit Electronica★ ·
Lo-fi Hip Hop★ · Synthwave · Ambient · Spooky Surf★

A genre is one JSON file in `sl2/genres/`: tempo range, scales, chord moves, song forms, drum patterns per energy level, bass
style, lead rhythms, tracks with their sounds and send levels, and the reference fingerprint.

## Layout

```
sl2.py              start the app / `make` from the command line
sl2/compose.py      the composer (form, harmony, drums, bass, chords, arps, riffs, fx)
sl2/melody.py       motif-based hooks + the melody critic
sl2/theory.py       keys, scales, chords, voice leading, per-part seeds
sl2/synth.py        every instrument and drum, synthesized with numpy
sl2/render.py       parallel cached stems, auto-gain, sidechain, sends, ref-steered master
sl2/analyze.py      reference analysis (tempo, key, drums, sections, tone, loudness, width, pump)
sl2/prompt.py       text description -> settings
sl2/store.py        songs, versions, jobs, exports
sl2/server.py       local HTTP server + API
sl2/ui/             the skin (index.html, skin.css, app.js, fonts)
sl2/genres/         genre packs
tools/analyze_refs.py   measure reference tracks into numbers
```

## Tests

```
python -m pytest -q tests
```

## License

MIT. Fonts: Space Grotesk and VT323, both under the SIL Open Font License (`sl2/ui/fonts/`). The skin is an original design
inspired by classic late-90s media players. It isn't affiliated with or based on any product's artwork, names or logos.
