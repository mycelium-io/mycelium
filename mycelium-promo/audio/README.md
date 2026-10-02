<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 Mycelium Contributors -->

# The demo's sound

A gentle drone under the whole take, and the clicks and keystrokes of the
person driving it, placed where they show in the picture. Generated from
source, so it follows the take when the take changes.

The drone is mycelium's; everything else is shotkit's (`shotkit/src/audio`,
see the Sound section of `shotkit/README.md`):

```
audio/score.mjs    the drone, rendered as a stereo pair for shotkit to use as the bed
audio/build.mjs    the drone under the take's clicks and keys, mixed and muxed by shotkit
```

```bash
node mycelium-promo/record.mjs                                         # records the take and gives it this sound
node mycelium-promo/audio/build.mjs mycelium-promo/mycelium-demo.mp4   # re-mix a take without re-recording it
```

## The drone

The bed of the earlier promo score, and nothing else: sine partials on a D
chord, each breathing on its own slow LFO so the texture never repeats;
pink noise through a slowly moving bandpass; a pad on the chord's upper tones
whose filter never opens past ~1.4 kHz; and a sub swell every two beats, all
through a long hall. Bare D and A to open, D minor through the body, bare again
to close.

## Clicks, keys and the mix (shotkit)

Every take writes `<video>.sounds.json` beside it: each click and lone key press
at the second it shows in the finished video, and each typed string with the
span it went in over. A click is a soft low "tock", a key a quiet dark tick, a
little different each time and spread unevenly across its string's span, and
Enter a heavier key.

The drone is brought to −23 LUFS, the clicks sit at a fixed size over it, the
pair is set to −19 LUFS, and the drone is then trimmed 6 dB under, so the
clicks and keys sit forward. `build.mjs` prints the finished loudness and true
peak.
