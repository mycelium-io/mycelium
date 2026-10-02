// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Bus processing and metering: a glue compressor, a look-ahead limiter, and
 * ITU-R BS.1770-4 loudness, so how loud a soundtrack is comes out of the build
 * as a number rather than a guess, and a track can be normalized to a stated
 * loudness instead of to its loudest click.
 */

import { clamp } from "./dsp.mjs";

/**
 * Slow stereo-linked glue compressor. Low ratio, soft knee, and the sidechain
 * reads a smoothed mean square rather than a peak, so clicks keep their
 * transients and only sustained material is held down. Works in place.
 */
export function glue(L, R, sr, {
  thresholdDb = -22, ratio = 1.7, kneeDb = 10,
  attackMs = 60, releaseMs = 700, detectorMs = 45, makeupDb = 0,
} = {}) {
  const atk = Math.exp(-1 / ((attackMs / 1000) * sr));
  const rel = Math.exp(-1 / ((releaseMs / 1000) * sr));
  const det = Math.exp(-1 / ((detectorMs / 1000) * sr));
  const makeup = Math.pow(10, makeupDb / 20);
  // A transient shorter than the detector window barely moves the smoothed
  // mean square, which is what keeps a click off the sidechain.
  let ms = 0;
  let gr = 0;
  let maxGr = 0;

  for (let i = 0; i < L.length; i++) {
    const p = (L[i] * L[i] + R[i] * R[i]) * 0.5;
    ms = p + (ms - p) * det;
    const db = 10 * Math.log10(ms + 1e-12);

    // Soft knee: quadratic interpolation across the knee width.
    const over = db - thresholdDb;
    let target;
    if (over <= -kneeDb / 2) target = 0;
    else if (over >= kneeDb / 2) target = over * (1 - 1 / ratio);
    else {
      const x = over + kneeDb / 2;
      target = ((1 - 1 / ratio) * x * x) / (2 * kneeDb);
    }
    const coef = target > gr ? atk : rel;
    gr = target + (gr - target) * coef;
    if (gr > maxGr) maxGr = gr;

    const g = Math.pow(10, -gr / 20) * makeup;
    L[i] *= g;
    R[i] *= g;
  }
  return { maxGainReductionDb: maxGr };
}

/**
 * Look-ahead peak limiter. A gain curve is computed as each sample arrives
 * (instant attack, smooth release), and each sample leaves the look-ahead
 * delay at the lowest gain in its window: so the gain is already down when a
 * transient lands, and no sample can leave above the ceiling, since its own
 * arrival is in its window. Works in place. `ceiling` is linear.
 */
export function limit(L, R, sr, { ceiling = 0.89, lookaheadMs = 4, releaseMs = 120 } = {}) {
  const n = L.length;
  const la = Math.max(1, Math.round((lookaheadMs / 1000) * sr));
  const rel = Math.exp(-1 / ((releaseMs / 1000) * sr));
  const gains = new Float64Array(n);
  let gain = 1;
  for (let i = 0; i < n; i++) {
    const peak = Math.max(Math.abs(L[i]), Math.abs(R[i]));
    const target = peak > ceiling ? ceiling / peak : 1;
    gain = target < gain ? target : target + (gain - target) * rel;
    gains[i] = gain;
  }

  // Sliding minimum of gains[j .. j+la] with a monotonic deque of indices.
  const dq = new Int32Array(n);
  let head = 0;
  let tail = 0;
  let next = 0;
  let minGain = 1;
  for (let j = 0; j < n; j++) {
    const edge = Math.min(n - 1, j + la);
    for (; next <= edge; next++) {
      while (tail > head && gains[dq[tail - 1]] >= gains[next]) tail--;
      dq[tail++] = next;
    }
    while (dq[head] < j) head++;
    const g = gains[dq[head]];
    if (g < minGain) minGain = g;
    L[j] = clamp(L[j] * g, -1, 1);
    R[j] = clamp(R[j] * g, -1, 1);
  }
  return { maxGainReductionDb: -20 * Math.log10(minGain) };
}

// ── ITU-R BS.1770-4 loudness ───────────────────────────────────────────
// K-weighting is a high shelf (the head) then a highpass. The standard
// publishes coefficients for 48kHz only. These come from the bilinear transform
// of its analog design, the derivation libebur128 uses, which reproduces the
// published 48kHz coefficients exactly and holds at any other rate. (A cookbook
// shelf with the same corner and gain does not: it lands 0.2 dB off at 1kHz.)

function kWeighting(sr) {
  const shelf = (() => {
    const f0 = 1681.974450955533;
    const G = 3.999843853973347;
    const Q = 0.7071752369554196;
    const K = Math.tan((Math.PI * f0) / sr);
    const Vh = Math.pow(10, G / 20);
    const Vb = Math.pow(Vh, 0.4996667741545416);
    const a0 = 1 + K / Q + K * K;
    return {
      b: [(Vh + (Vb * K) / Q + K * K) / a0, (2 * (K * K - Vh)) / a0, (Vh - (Vb * K) / Q + K * K) / a0],
      a: [1, (2 * (K * K - 1)) / a0, (1 - K / Q + K * K) / a0],
    };
  })();
  const hpf = (() => {
    const f0 = 38.13547087602444;
    const Q = 0.5003270373238773;
    const K = Math.tan((Math.PI * f0) / sr);
    const a0 = 1 + K / Q + K * K;
    return { b: [1, -2, 1], a: [1, (2 * (K * K - 1)) / a0, (1 - K / Q + K * K) / a0] };
  })();
  return [shelf, hpf];
}

function biquad(x, { b, a }) {
  const y = new Float64Array(x.length);
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let i = 0; i < x.length; i++) {
    const v = b[0] * x[i] + b[1] * x1 + b[2] * x2 - a[1] * y1 - a[2] * y2;
    x2 = x1; x1 = x[i]; y2 = y1; y1 = v;
    y[i] = v;
  }
  return y;
}

/** Mean-square power per block, summed over channels, after K-weighting. */
function blockPowers(L, R, sr, blockSec, hopSec) {
  const [shelf, hpf] = kWeighting(sr);
  const chans = [L, R].map((c) => biquad(biquad(Float64Array.from(c), shelf), hpf));
  const block = Math.round(blockSec * sr);
  const hop = Math.round(hopSec * sr);
  const powers = [];
  for (let s = 0; s + block <= L.length; s += hop) {
    let z = 0;
    for (const c of chans) {
      let acc = 0;
      for (let i = s; i < s + block; i++) acc += c[i] * c[i];
      z += acc / block;
    }
    powers.push(z);
  }
  return powers;
}

const loud = (z) => -0.691 + 10 * Math.log10(z + 1e-12);

/** Integrated loudness in LUFS, with the absolute and relative gates applied. */
export function lufs(L, R, sr) {
  const above = blockPowers(L, R, sr, 0.4, 0.1).filter((z) => loud(z) > -70);
  if (!above.length) return -Infinity;
  const relGate = loud(above.reduce((a, z) => a + z, 0) / above.length) - 10;
  const gated = above.filter((z) => loud(z) > relGate);
  if (!gated.length) return -Infinity;
  return loud(gated.reduce((a, z) => a + z, 0) / gated.length);
}

/** Loudness range (LRA) in LU: the spread the ear reads as "dynamic". */
export function lra(L, R, sr) {
  const vals = blockPowers(L, R, sr, 3, 1).map(loud).filter((l) => l > -70);
  if (vals.length < 2) return 0;
  // The relative gate sits 20 LU under the mean power, not the mean of the dBs.
  const mean = loud(vals.reduce((a, l) => a + Math.pow(10, (l + 0.691) / 10), 0) / vals.length);
  const above = vals.filter((v) => v > mean - 20).sort((a, b) => a - b);
  const pick = (p) => above[clamp(Math.round(p * (above.length - 1)), 0, above.length - 1)];
  return pick(0.95) - pick(0.1);
}

/** Gain (linear) that brings a track to `target` LUFS. */
export function gainTo(L, R, sr, target) {
  const now = lufs(L, R, sr);
  return Number.isFinite(now) ? Math.pow(10, (target - now) / 20) : 1;
}

/** The largest sample, in dBFS. Not the true peak: see `truePeakDb`. */
export function samplePeakDb(L, R) {
  let p = 0;
  for (let i = 0; i < L.length; i++) p = Math.max(p, Math.abs(L[i]), Math.abs(R[i]));
  return 20 * Math.log10(p + 1e-12);
}

/**
 * True peak in dBTP: the peak of the signal between samples, estimated by 4x
 * oversampling as BS.1770 describes. A lossy encode (AAC, Opus) reconstructs
 * those in-between values, so it is the true peak that has to stay under 0.
 */
export function truePeakDb(L, R) {
  const P = 4;
  const TAPS = 12; // per phase
  const h = [];
  for (let ph = 0; ph < P; ph++) {
    const row = new Float64Array(TAPS);
    for (let k = 0; k < TAPS; k++) {
      const x = k - TAPS / 2 + 1 - ph / P;
      const sinc = x === 0 ? 1 : Math.sin(Math.PI * x) / (Math.PI * x);
      const win = 0.5 * (1 + Math.cos((Math.PI * x) / (TAPS / 2 + 1)));
      row[k] = sinc * win;
    }
    h.push(row);
  }
  let peak = 0;
  for (const c of [L, R]) {
    for (let i = TAPS; i < c.length; i++) {
      for (let ph = 0; ph < P; ph++) {
        const row = h[ph];
        let acc = 0;
        for (let k = 0; k < TAPS; k++) acc += c[i - k] * row[k];
        const a = Math.abs(acc);
        if (a > peak) peak = a;
      }
    }
  }
  return 20 * Math.log10(peak + 1e-12);
}
