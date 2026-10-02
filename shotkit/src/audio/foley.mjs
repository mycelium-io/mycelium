// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The sound of the person driving the take: a soft low "tock" per click and a
 * quiet tick per keystroke, placed from the take's cues (cues.mjs).
 *
 * Every sound is synthesized, slightly different each time from a seeded
 * source, so a run of keys reads as a hand typing rather than a sample on
 * repeat, and a re-render is the same file. They go through a short plate so
 * they sit in a room rather than on top of the mix.
 */

import { FDNReverb, SVF, TAU, makeBus, rng } from "./dsp.mjs";

/** A soft, low "tock": a pitched body that falls a little, under a short tap. */
export function tock(bus, t, r, gain = 1) {
  const sr = bus.sr;
  const i0 = Math.round(t * sr);
  const len = Math.round(sr * 0.07);
  const svf = new SVF(sr);
  const f0 = 230 + r() * 30;
  const pan = (r() - 0.5) * 0.2;
  let ph = 0;
  for (let k = 0; k < len; k++) {
    const u = k / sr;
    const body = Math.sin(TAU * ph) * Math.exp(-u * 70);
    ph += (f0 * (1 - 0.35 * Math.min(1, u / 0.03))) / sr;
    const tap = svf.bp(r() * 2 - 1, 1900, 1.8) * Math.exp(-u * 600);
    bus.add(i0 + k, (body * 0.9 + tap * 0.5) * 0.11 * gain, pan, 0.18);
  }
}

/** One key: a short, dark tick, a little different every time. */
export function tick(bus, t, r, gain = 1) {
  const sr = bus.sr;
  const i0 = Math.round(t * sr);
  const len = Math.round(sr * 0.04);
  const svf = new SVF(sr);
  const centre = 2600 + r() * 1400;
  const thumpF = 150 + r() * 40;
  const g = (0.75 + r() * 0.25) * gain;
  const pan = (r() - 0.5) * 0.35;
  for (let k = 0; k < len; k++) {
    const u = k / sr;
    const click = svf.bp(r() * 2 - 1, centre, 2.0) * Math.exp(-u * 520);
    const thump = Math.sin(TAU * thumpF * u) * Math.exp(-u * 140);
    bus.add(i0 + k, (click * 0.65 + thump * 0.35) * 0.065 * g, pan, 0.12);
  }
}

/** How much louder a key pressed on its own (Enter, Escape) is than a typed one. */
const LONE_KEY_GAIN = 2.4;

/**
 * Put every cue on a bus. A click is a tock, a lone key a heavy tick, and a
 * typed string a tick per character spread unevenly over the span it went in
 * over (or ~55ms apart when the span is unknown).
 * @param {ReturnType<typeof makeBus>} bus
 * @param {{t:number, t1?:number, kind:string, chars?:number}[]} cues
 */
export function placeCues(bus, cues, { seed = 0xc11c, clickGain = 1, keyGain = 1 } = {}) {
  const r = rng(seed);
  for (const e of cues) {
    if (e.kind === "click") tock(bus, e.t, r, clickGain);
    else if (e.kind === "key") tick(bus, e.t, r, LONE_KEY_GAIN * keyGain);
    else if (e.kind === "type" && e.chars > 0) {
      const t1 = typeof e.t1 === "number" && e.t1 > e.t ? e.t1 : e.t + e.chars * 0.055;
      const step = (t1 - e.t) / e.chars;
      for (let c = 0; c < e.chars; c++) {
        // A little unevenness, as a hand types.
        tick(bus, e.t + c * step + (r() - 0.5) * step * 0.35, r, keyGain);
      }
    }
  }
}

/**
 * The foley track for a video `duration` seconds long: the cues placed, through
 * a short plate. Unleveled; the mix sets its loudness.
 * @returns {{L: Float64Array, R: Float64Array}}
 */
export function renderFoley(duration, cues, sr = 48000, opts = {}) {
  const n = Math.ceil(duration * sr);
  const bus = makeBus(sr, n);
  placeCues(bus, cues, opts);
  const plate = new FDNReverb(sr, { rt60: 0.6, damp: 5200, preDelay: 0.006, modDepth: 0.6, modRate: 0.21, seed: 29 });
  const L = new Float64Array(n);
  const R = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const [pl, pr] = plate.run(bus.sendA[i]);
    L[i] = bus.L[i] + pl * 0.5;
    R[i] = bus.R[i] + pr * 0.5;
  }
  return { L, R };
}
