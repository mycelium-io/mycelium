# The backing track

A 107-second synthetic score for `../index.html`, generated from source rather
than dropped in as a sample. `npm run audio` renders it to
`../assets/mycelium-score.mp3`, which the composition loads as an `<audio>`
clip on track 11.

```
audio/dsp.mjs      oscillators, filters, envelopes, the FDN reverb, WAV encoding
audio/master.mjs   glue compressor, look-ahead limiter, BS.1770-4 loudness meter
audio/score.mjs    the piece: the section table, the cue table, the voices
audio/build.mjs    render → WAV → MP3
```

## Why generate it

The promo is a code-defined video; a code-defined score keeps the two in the
same repository under the same review. `score.mjs`'s cue times are read out of
`index.html`'s GSAP calls, so when a beat moves the score can move with it —
which is not something you can do to a licensed loop. Re-render after touching
either file.

## The piece

One organism, not nine cues: a drone bed and a filtered-noise substrate run
unbroken for the full duration, and everything else grows out of them. Two
tables drive it. `SECTIONS` gives each of the video's scenes a chord, a
brightness and a pitch pool. `CUES` places motifs on individual frames — a
terminal line, a service coming up healthy, an agent registering, a round
advancing.

The argument is carried in the third of the chord:

| | harmony | what is on screen |
| --- | --- | --- |
| 0–13.8s | D and A, no third | the hero card; a bell, and a long way down |
| 13.8–52.2s | the third arrives as **F** — D minor | install, room, agents |
| 61.6–81.4s | the chord drops its third entirely; @rowan's figure lands on **F**, @avery's on **F#** | the five NEGMAS rounds |
| 81.4s | rowan takes F# and a sustained voice glides the semitone | the offer table locks green |
| 81.4–100.4s | D–F#–A–E, major | the plan compiles, the room is distilled |
| 100.4–107s | back to bare D and A, an octave wider | the outro |

The generative layer is the one that carries the name. A pluck that fires may
fork — a child a fifth or an octave away, which may fork again — so the
texture spreads outward from each strike rather than repeating a pattern.
Forks snap to the section's own pitch set, so a branch is always in the mode
it lands in. Everything is seeded: the same colony grows every render.

## Verifying a change

Nothing here can be checked by reading it. The build prints what it measured:

```
  -17.0 LUFS · LRA 12.2 LU · true peak -1.9 dBFS
  glue -4.0 dB · limiter -0.7 dB
```

`-17 LUFS` is the target, set in `score.mjs`; the meter is a BS.1770-4
implementation in `master.mjs` and agrees with `ffmpeg -af ebur128` to a tenth
of a decibel. If a change moves the loudness, the limiter reduction or the
loudness range much, find out what it did before assuming it sounds fine. A
voice that renders silently — a mistuned envelope, a loop that exits on its
own first sample — reads perfectly well as source and shows up only here.

`npm run audio -- --wav` keeps the intermediate 48kHz WAV, which is what to
point an analyzer at.

## Known: 21ms

Rendering through `hyperframes render` puts the track 1024 samples (21.3ms,
0.64 of a frame at 30fps) later than the source. The delay is not the MP3 —
ffmpeg decodes the asset sample-exact — it comes from the render pipeline's
audio stage. It is inside broadcast sync tolerance and inaudible on a bed
with no transient sharper than a woodblock, so it is measured and left rather
than papered over with an offset that would rot the first time the pinned
`hyperframes` version moves.
