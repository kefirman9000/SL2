# SL2 roadmap

## Done in 2.0

- [x] Song document with versions (undo = parent), locks, per-part re-rolls
- [x] Genre packs with their own drums, sounds, forms and mix targets; uniqueness test
- [x] 11 genres modelled on reference tracks; ref-steered master (tone, width, low-end mono, loudness)
- [x] Motif-based hooks with a melody critic; voice-led chords; chords chosen to fit a locked melody
- [x] Parallel, content-cached stem rendering; auto-gain; kick-driven sidechain
- [x] Reference analyser + genre matcher; text prompt parser
- [x] Classic media-player skin: player, mixer faders, playlist, composer, editor with piano roll, info
- [x] Exports: WAV master, stems, MIDI, song file

## Done in 2.1

- [x] Phrase-level variation, staggered entries/exits, filter-sweep automation, evolving later drops, key lift
- [x] Call and response, trance breakdown theme, house chops, techno sequence
- [x] Melody critic that rewards tension/resolution, question/answer phrasing and syncopation
- [x] Major V / borrowed iv, chord anticipation, bass approach notes, consistent chord colour, no semitone clusters
- [x] Feel controls (fills, hats, ghosts, build-ups, FX, variation); club and loop lengths; 3-5 forms per genre
- [x] Section tools, more like this / something different, A/B, genre search / favourites, open song files, MP3, diagnostics
- [x] Windows app and installer (built and smoke-tested in CI), Windows launcher for the source, Windows CI

## Next

- [ ] **Better drum transcription** from references (separate the kick from the sub with transient detection), so drum
      patterns can be learned from the references too, not just tempo and tone.
- [ ] **A more reliable key finder** (bass-weighted chroma, tuned to dense electronic mixes).
- [ ] **More reference genres:** send 2-3 tracks per style.
- [ ] **Live preview while editing:** play the piano roll's part through the browser while you edit, before rendering.
- [ ] **Vocals:** formant-synthesized "ooh / aah" and chopped vocal stabs.
- [ ] **Desktop window:** open the skin in its own window (pywebview) at its native size, with movable / dockable windows.
- [ ] **Skins:** load other colour schemes for the same layout.
- [ ] **Faster synths:** numba kernels for the filter sweeps (wobble, acid, hoover) when numba is installed.
