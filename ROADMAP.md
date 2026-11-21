# Studio Lab 2 roadmap

Built next to Studio Lab 1, not as a big-bang rewrite: v1 stays the app you use, and each piece of v2 is checked
against v1 (same genres, same or better scores) before it replaces anything.

## Phase 1: foundations (started)

- [x] **Song document** (`sl2/song.py`): sections, tracks, clips, automation in one JSON file. The editor changes it
      directly instead of storing seeds plus patches and composing again.
- [x] **Genre packs** (`packs/`, `sl2/packs.py`): all 346 v1 genres as JSON with inheritance, converted by
      `tools/convert_v1_styles.py` and checked equal to v1.
- [x] **Look**: black & neon green and the Space Grotesk font are the defaults (`ui/theme.css`).
- [ ] **Families by sound, not by menu.** The 32 families come from v1's browsing groups, which only removes about a
      quarter of the repeated settings. Cluster genres by their actual settings (drums, bass, tempo, form) so `house`
      → `deep_house` → `tokyo_deep_house` is a chain of small overrides.
- [ ] **Full schema** for every setting (type, range, what it does). Settings that only one or two genres use
      (`eno_loops`, `granular`, `cut_meters` ...) become named **devices** in a registry that any genre can switch on.
- [ ] **Seeding**: every random choice seeded by (seed, genre, part). Test that seeds spread over all 12 keys
      (v1 picks Eb for 30% of songs and never C#, E, F# or B: `tools/check_v1_seed_keys.py`).

## Phase 2: sound engine

- [ ] Render tracks in parallel (they're independent until the mix), one process per core.
- [ ] Cache rendered notes by (sound, pitch, velocity, length).
- [ ] Mix in the browser: render stems once, then mute / solo / level / pan are instant.
- [ ] Plugin rigs (Surge XT, OB-Xf ...) as the default engine for house, trance, techno and DnB, still separate
      downloads so the MIT core stays separate from the GPL plugins. Recorded one-shots for electronic drums.
- [ ] Targets: section preview under 5 s, full song in about 15-20 s (v1: 80-100 s on one core).

## Phase 3: composition

- [ ] Write in levels: motif → phrase → section → song, with the repeat / vary plan (AABA, call and response,
      tension curve) stored in the genre pack.
- [ ] Chords and bass written together, with voice leading, secondary dominants, borrowed chords, key changes.
- [ ] "Write several, keep the best" for every part, not just the hook: chord tones on strong beats, register clashes,
      bass locked to kick, energy curve.
- [ ] Optional pack: a small open-weights MIDI model for melody infill, kept inside the genre's rules.

## Phase 4: editor and references

- [ ] Piano roll, undo / redo, loop a section while editing, A/B two takes, lock a part and regenerate around it.
- [ ] Export DAWproject (Bitwig, Studio One), plus MIDI and stems.
- [ ] Drop a reference track → tempo, key, sections, drum pattern per section, tone, loudness, pumping are measured
      and a genre variant plus fitness targets are written for you.

## Always: measurable quality

- [ ] Per-genre target numbers (loudness, tonal balance, kick/bass masking, fitness score), checked in CI.
- [ ] Seeds must give different songs (key, tempo, progression spread).
- [ ] A small blind A/B rating page, so "better" is judged by ear.
- [ ] Settings in three levels: Simple, Producer, Expert. Version-labelled switches become genre defaults.
