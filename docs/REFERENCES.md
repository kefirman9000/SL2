# Reference measurements

SL2's referenced genres were modelled on tracks you supplied. Only these numbers are kept - never the audio.
Measured with `tools/analyze_refs.py` (tempo with a genre hint, ITU-R BS.1770 loudness, 9-band tonal balance, side/mid width,
low-end side level, and pumping = how much the 300 Hz-3 kHz band dips and recovers on each beat).

| Genre | Tracks | BPM | LUFS | Width | Low-end side | Pump | Tonal balance 20 Hz → 11 kHz (dB, loudest band = 0) |
|---|---|---|---|---|---|---|---|
| Liquid DnB | 6 | 171–176 | -6.9 | 0.20 | -27 dB | 3.6 dB | -2 / -0 / -4 / -8 / -7 / -9 / -10 / -9 / -13 |
| Sunlit Electronica | 7 | 98–138 | -9.0 | 0.35 | -22 dB | 2.3 dB | -7 / -1 / -4 / -6 / -8 / -11 / -15 / -22 / -29 |
| Deep Dubstep | 8 | 140–143 | -8.6 | 0.15 | -32 dB | 6.6 dB | -0 / -7 / -10 / -13 / -13 / -13 / -16 / -18 / -23 |
| Melodic Deep House | 5 | 109–125 | -6.6 | 0.42 | -18 dB | 6.0 dB | -1 / -1 / -6 / -6 / -6 / -9 / -15 / -12 / -16 |
| Trance | 1 | 138–138 | -8.3 | 0.23 | -18 dB | 7.6 dB | 0 / -0 / -6 / -10 / -13 / -9 / -12 / -15 / -19 |
| Hard Electro | 1 | 142–142 | -8.6 | 0.30 | -12 dB | 1.1 dB | -0 / 0 / -2 / -4 / -8 / -7 / -7 / -10 / -18 |
| Spooky Surf | 1 | 154–154 | -14.2 | 0.54 | -6 dB | 1.4 dB | -19 / 0 / -5 / -10 / -5 / -6 / -5 / -12 / -17 |
| Lo-fi Hip Hop | 1 | 82–82 | -13.2 | 0.42 | -21 dB | 1.9 dB | -50 / -10 / 0 / -4 / -13 / -20 / -32 / -57 / -70 |
| Hard Trap | 1 | 140–140 | -9.9 | 0.13 | -34 dB | 14.9 dB | 0 / -5 / -11 / -13 / -11 / -13 / -14 / -12 / -17 |
| Memphis Phonk | 1 | 162–162 | -8.5 | 0.21 | -15 dB | 5.1 dB | 0 / -9 / -16 / -18 / -20 / -23 / -23 / -23 / -30 |
| Tech House | 1 | 126–126 | -9.1 | 0.21 | -20 dB | 7.7 dB | 0 / -3 / -8 / -13 / -9 / -12 / -15 / -14 / -20 |

What came from these, per genre:

- **Liquid DnB** (Netsky): 172–176 BPM; long bass-free intros (24–47 bars); 48–96-bar drops; bright top end; mono low end; loud (~−7 LUFS).
- **Sunlit Electronica** (Tycho): 112–126 BPM; wide; warm with a steep top-end roll-off; very little pumping; chords change every ~1.5–2 bars.
- **Deep Dubstep** (Skream, Benga, Kromestar, Distance, Joker): 140 BPM half-step; very narrow (0.09–0.25); sub-heavy and fully mono below 120 Hz; long low-end sections with short breakdowns.
- **Melodic Deep House** (Nora En Pure): 120–125 BPM; the widest of all (0.4–0.6); ~6 dB of pump; loud; 16-bar intros.
- **Trance** (Joop), **Hard Electro** (JFK / Bad Habit Boys), **Tech House** (Girl Unit / Claude VonStroke remix), **Hard Trap** (Waka Flocka Flame instrumental), **Memphis Phonk** (DJ Smokey), **Lo-fi Hip Hop** (tomcbumpz), **Spooky Surf** (the Munsters theme): one reference each - tempo, loudness, width, pump and tone.

Not reliable yet: the key finder (it leans to C and F major on dense mixes), and per-step kick patterns on bass-heavy tracks (the sub masks the kick).
Drum patterns therefore come from each style's standard grooves; snare placement did match (2 & 4 for DnB, 3 for half-step).
