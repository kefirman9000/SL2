# Studio Lab 2

The next version of [Studio Lab](https://github.com/kefirman9000/studio-lab), the local music generator, rebuilt so it can grow without
getting harder to change: a song you can edit directly, genres as data instead of code, a faster sound engine, and
composition that plans a song instead of picking notes one at a time.

**Status: foundations.** Nothing makes sound yet. Studio Lab 1 stays the app you use while this is built; see
[ROADMAP.md](ROADMAP.md) for the plan and [docs/V1_FINDINGS.md](docs/V1_FINDINGS.md) for what it is based on.

## What's here

| Path | What it is |
|---|---|
| `sl2/song.py` | The **song document**: sections, tracks, clips of notes, automation. Saves to JSON. The composer writes it, the editor changes it, the engine reads it. |
| `sl2/packs.py` | Loads **genre packs**, resolves what each one inherits, checks it. |
| `packs/` | All 346 Studio Lab 1 genres as JSON packs, grouped into 32 families (`_family.json` holds what a group shares). Made by the converter below. |
| `tools/convert_v1_styles.py` | Converts Studio Lab 1's `styles.py` into packs. Run it again whenever v1 gains a genre. |
| `tools/check_v1_seed_keys.py` | Shows Studio Lab 1's key bias (seed N gives the same key in every genre). |
| `ui/theme.css` | The look: black & neon green, Space Grotesk (bundled, SIL Open Font License). |
| `tests/` | Every pack loads and is valid; with `SL1_PATH` set, every pack equals the v1 genre it came from. Song save/load. |

## Try it

```
pip install -r requirements.txt
python -m pytest tests                                   # packs + song document
SL1_PATH=../studio-lab python -m pytest tests             # ... and checked against Studio Lab 1
python tools/convert_v1_styles.py ../studio-lab --out packs   # regenerate the packs from v1
python tools/check_v1_seed_keys.py ../studio-lab          # the key bias, measured
```

## License

MIT, like Studio Lab 1. The Space Grotesk font is under the SIL Open Font License (`ui/fonts/OFL-SpaceGrotesk.txt`).
