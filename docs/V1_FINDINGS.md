# What Studio Lab 1 (1.96) looks like inside

Measured on 2026-11-21 from a fresh clone of kefirman9000/studio-lab.

## Size and shape

- About 45,000 lines of Python. `styles.py` is 11,700 lines: 346 genres as dicts using 138 different settings,
  39-58 per genre. About 28 settings are used by only one or two genres (one-off switches).
- `compose()` is one 952-line function; `render()` is 433 lines. `Options` has about 100 fields, many labelled with
  the version that added them (1.85, 1.90, 1.93 ...).
- The UI is one 2,690-line `ui.html` (vanilla JS) talking to a standard-library HTTP server.

## Speed

Offline render, numpy only, tracks one after another (no numba on the test machine):

| Song | Time |
|---|---|
| house, seed 3 | 81 s |
| liquid_dnb, seed 5 | 101 s |

In the house song the congas and pads took about 12 s each.

## Key bias

The harmony random generator is seeded by the seed only (`opts.seed * 1009 + 1`), not the genre, so a seed gives
nearly the same key in every genre:

```
seed 1: house=Ab minor  techno=A minor   trance=Ab minor  dubstep=Eb minor    liquid_dnb=A minor
seed 2: house=Eb dorian techno=D minor   trance=Eb minor  dubstep=Eb phrygian liquid_dnb=D minor
seed 3: house=Eb dorian techno=Bb minor  trance=Eb minor  dubstep=Eb phrygian liquid_dnb=Bb minor
```

Over 40 songs (5 genres × seeds 1-8): Eb 30%, G and A 17.5% each, C 12.5%, and C#, E, F#, B never.
Reproduce with `python tools/check_v1_seed_keys.py ../studio-lab`.

## Worth keeping

Plugins in their own process, reference analysis and genre matching, the fitness and mix checks, MIDI / LMMS /
Tracktion exports, the download safety checks, the self-updater.
