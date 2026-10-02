<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 Mycelium Contributors -->

# The demo's sound

A gentle drone under the whole take, and the clicks and keystrokes of the
person driving it, placed where they land in the picture. Generated from
source, so it follows the take when the take changes.

```
audio/dsp.mjs      oscillators, filters, envelopes, the FDN reverb, WAV encoding
audio/master.mjs   glue compressor, look-ahead limiter, BS.1770-4 loudness meter
audio/score.mjs    the drone, the click and the key, and the mix
audio/build.mjs    render → WAV → muxed into the video as AAC
```

```bash
node mycelium-promo/record.mjs                               # the take, and mycelium-demo.mp4.sounds.json beside it
node mycelium-promo/audio/build.mjs mycelium-promo/mycelium-demo.mp4   # → mycelium-demo-sound.mp4
```

## The drone

The bed of the earlier promo score, and nothing else: sine partials on a D
chord, each breathing on its own slow LFO so the texture never repeats;
pink noise through a slowly moving bandpass; a pad on the chord's upper tones
whose filter never opens past ~1.4 kHz; and a sub swell every two beats. Bare D
and A to open, D minor through the body, bare again to close. It is leveled to
−23 LUFS before the clicks go on, so it stays under the video.

## Clicks and keys

shotkit writes `<video>.sounds.json` beside a staged take: each click and lone
key press at the second it lands in the finished video, and each typed string
with the span it went in over. A click is a soft low "tock" (a short pitched
body that falls a little, under a tap); a key is a quiet dark tick, a little
different each time, spread unevenly across its string's span; Enter is a
heavier key. The finished track is −19 LUFS.
