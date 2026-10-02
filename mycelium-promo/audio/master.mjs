// Bus processing and metering for the backing track.
//
// The score's dynamic range is wider than a video bed wants — the drone at 4s
// and the consensus chord at 82s are twenty decibels apart. The range is
// closed here rather than by flattening the writing, and the result is
// normalized to a stated loudness target instead of to a peak, so how loud
// the track is is a number in the build output rather than a guess.

import { clamp } from './dsp.mjs';

/**
 * Slow stereo-linked glue compressor. Low ratio, soft knee, and the sidechain
 * reads a smoothed mean square rather than a peak, so the ticks and plucks
 * keep their transients and only sustained material is held down.
 */
export function glue(L, R, sr, {
  thresholdDb = -22, ratio = 1.7, kneeDb = 10,
  attackMs = 60, releaseMs = 700, detectorMs = 45, makeupDb = 0,
} = {}) {
  const atk = Math.exp(-1 / ((attackMs / 1000) * sr));
  const rel = Math.exp(-1 / ((releaseMs / 1000) * sr));
  const det = Math.exp(-1 / ((detectorMs / 1000) * sr));
  const makeup = Math.pow(10, makeupDb / 20);
  let ms = 0;  // smoothed mean square — a transient shorter than the window
               // barely moves it, which is what keeps ticks off the sidechain
  let gr = 0;  // gain reduction in dB
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
 * Look-ahead peak limiter. The delay line holds the signal while the gain
 * curve is computed on what is about to arrive, so a transient is turned
 * down before it lands rather than clipped after it.
 */
export function limit(L, R, sr, { ceiling = 0.89, lookaheadMs = 4, releaseMs = 120 } = {}) {
  const n = L.length;
  const la = Math.max(1, Math.round((lookaheadMs / 1000) * sr));
  const rel = Math.exp(-1 / ((releaseMs / 1000) * sr));
  const dl = new Float64Array(la);
  const dr = new Float64Array(la);
  let w = 0;
  let gain = 1;
  let minGain = 1;

  for (let i = 0; i < n + la; i++) {
    const inL = i < n ? L[i] : 0;
    const inR = i < n ? R[i] : 0;
    const peak = Math.max(Math.abs(inL), Math.abs(inR));
    const target = peak > ceiling ? ceiling / peak : 1;
    gain = target < gain ? target : target + (gain - target) * rel;
    if (gain < minGain) minGain = gain;

    const outL = dl[w];
    const outR = dr[w];
    dl[w] = inL;
    dr[w] = inR;
    w = (w + 1) % la;

    const j = i - la;
    if (j >= 0 && j < n) {
      L[j] = clamp(outL * gain, -1, 1);
      R[j] = clamp(outR * gain, -1, 1);
    }
  }
  return { maxGainReductionDb: -20 * Math.log10(minGain) };
}

// ── ITU-R BS.1770-4 loudness ───────────────────────────────────────────
// K-weighting: a high shelf approximating the head, then a highpass. The
// published coefficients are for 48kHz, which is what the track renders at.
const SHELF = { b: [1.53512485958697, -2.69169618940638, 1.19839281085285], a: [1, -1.69065929318241, 0.73248077421585] };
const HPF = { b: [1.0, -2.0, 1.0], a: [1, -1.99004745483398, 0.99007225036621] };

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

/** Integrated loudness in LUFS, with the absolute and relative gates applied. */
export function lufs(L, R, sr) {
  if (sr !== 48000) throw new Error('the K-weighting coefficients here are 48kHz-only');
  const chans = [L, R].map((c) => biquad(biquad(Float64Array.from(c), SHELF), HPF));
  const block = Math.round(0.4 * sr);
  const hop = Math.round(0.1 * sr);
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
  const loud = (z) => -0.691 + 10 * Math.log10(z + 1e-12);

  const above = powers.filter((z) => loud(z) > -70);
  if (!above.length) return -Infinity;
  const relGate = loud(above.reduce((a, z) => a + z, 0) / above.length) - 10;
  const gated = above.filter((z) => loud(z) > relGate);
  if (!gated.length) return -Infinity;
  return loud(gated.reduce((a, z) => a + z, 0) / gated.length);
}

/** Loudness range (LRA), the spread the ear reads as "dynamic". */
export function lra(L, R, sr) {
  const chans = [L, R].map((c) => biquad(biquad(Float64Array.from(c), SHELF), HPF));
  const block = Math.round(3 * sr);
  const hop = Math.round(1 * sr);
  const vals = [];
  for (let s = 0; s + block <= L.length; s += hop) {
    let z = 0;
    for (const c of chans) {
      let acc = 0;
      for (let i = s; i < s + block; i++) acc += c[i] * c[i];
      z += acc / block;
    }
    const l = -0.691 + 10 * Math.log10(z + 1e-12);
    if (l > -70) vals.push(l);
  }
  if (vals.length < 2) return 0;
  const above = vals.filter((v) => v > vals.reduce((a, b) => a + b, 0) / vals.length - 20);
  above.sort((a, b) => a - b);
  const pick = (p) => above[clamp(Math.round(p * (above.length - 1)), 0, above.length - 1)];
  return pick(0.95) - pick(0.1);
}

export const truePeakDb = (L, R) => {
  let p = 0;
  for (let i = 0; i < L.length; i++) p = Math.max(p, Math.abs(L[i]), Math.abs(R[i]));
  return 20 * Math.log10(p + 1e-12);
};
