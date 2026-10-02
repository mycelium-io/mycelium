// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Signal primitives for a take's soundtrack: a seeded random source, note
 * names, filters, noise, a reverb, envelopes and wavetables. Sample-rate
 * agnostic and allocation-free in the inner loop, so a two-minute track renders
 * in seconds in plain JavaScript.
 *
 * Nothing here calls Math.random: a soundtrack rendered twice from the same
 * cues is the same file, the way a staged take's backdrop is the same scene.
 */

export const TAU = Math.PI * 2;

/** Seeded PRNG (mulberry32), returning floats in [0, 1). */
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const clamp = (x, lo, hi) => (x < lo ? lo : x > hi ? hi : x);
export const lerp = (a, b, t) => a + (b - a) * t;
/** Decibels to a linear gain. */
export const dbToGain = (db) => Math.pow(10, db / 20);

/** 12-TET from A4=440. Note names as "D2", "F#3", "Bb4". */
const SEMITONES = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
export function hz(note) {
  const m = /^([A-G])([#b]?)(-?\d+)$/.exec(note);
  if (!m) throw new Error(`bad note: ${note}`);
  const semi = SEMITONES[m[1]] + (m[2] === "#" ? 1 : m[2] === "b" ? -1 : 0);
  const midi = (Number(m[3]) + 1) * 12 + semi;
  return 440 * Math.pow(2, (midi - 69) / 12);
}

// ── Filters ────────────────────────────────────────────────────────────
export class OnePole {
  constructor(sr, cutoff) {
    this.sr = sr;
    this.z = 0;
    this.setCutoff(cutoff);
  }
  setCutoff(f) {
    this.a = Math.exp((-TAU * clamp(f, 1, this.sr * 0.49)) / this.sr);
  }
  lp(x) {
    this.z = x + this.a * (this.z - x);
    return this.z;
  }
  hp(x) {
    return x - this.lp(x);
  }
}

/**
 * Topology-preserving state-variable filter (Zavalishin). Stable when the
 * cutoff is swept every sample.
 */
export class SVF {
  constructor(sr) {
    this.sr = sr;
    this.ic1 = 0;
    this.ic2 = 0;
    this.g = 0;
    this.k = 1;
    this.out = { lp: 0, bp: 0, hp: 0 };
  }
  set(cutoff, q) {
    this.g = Math.tan((Math.PI * clamp(cutoff, 8, this.sr * 0.47)) / this.sr);
    this.k = 1 / clamp(q, 0.4, 24);
  }
  run(x) {
    const { g, k } = this;
    const a1 = 1 / (1 + g * (g + k));
    const v1 = a1 * (this.ic1 + g * (x - this.ic2));
    const v2 = this.ic2 + g * v1;
    this.ic1 = 2 * v1 - this.ic1;
    this.ic2 = 2 * v2 - this.ic2;
    // One object reused, not one per sample.
    this.out.lp = v2;
    this.out.bp = v1;
    this.out.hp = x - k * v1 - v2;
    return this.out;
  }
  lp(x, cutoff, q) {
    this.set(cutoff, q);
    return this.run(x).lp;
  }
  bp(x, cutoff, q) {
    this.set(cutoff, q);
    return this.run(x).bp;
  }
  hp(x, cutoff, q) {
    this.set(cutoff, q);
    return this.run(x).hp;
  }
}

export class DCBlock {
  constructor() {
    this.x1 = 0;
    this.y1 = 0;
  }
  run(x) {
    const y = x - this.x1 + 0.9985 * this.y1;
    this.x1 = x;
    this.y1 = y;
    return y;
  }
}

/** Voss-McCartney pink noise: a hiss without white noise's top-end bite. */
export class PinkNoise {
  constructor(rand) {
    this.rand = rand;
    this.rows = new Float64Array(7);
    this.running = 0;
    this.counter = 0;
  }
  next() {
    const r = this.rand;
    this.counter = (this.counter + 1) >>> 0;
    let n = this.counter;
    for (let i = 0; i < 7; i++) {
      if ((n & 1) === 0) {
        this.running -= this.rows[i];
        this.rows[i] = r() * 2 - 1;
        this.running += this.rows[i];
        break;
      }
      n >>>= 1;
    }
    return (this.running + (r() * 2 - 1)) * 0.16;
  }
}

// ── Delay / reverb ─────────────────────────────────────────────────────
export class Delay {
  constructor(maxSamples) {
    this.buf = new Float64Array(Math.max(4, Math.ceil(maxSamples)));
    this.w = 0;
  }
  write(x) {
    this.buf[this.w] = x;
    this.w = (this.w + 1) % this.buf.length;
  }
  /** Fractional read, linearly interpolated, `d` samples back. */
  read(d) {
    const n = this.buf.length;
    let p = this.w - clamp(d, 1, n - 2);
    while (p < 0) p += n;
    const i = Math.floor(p);
    const f = p - i;
    return this.buf[i] * (1 - f) + this.buf[(i + 1) % n] * f;
  }
}

class Allpass {
  constructor(samples, g) {
    this.d = new Delay(samples + 4);
    this.n = samples;
    this.g = g;
  }
  run(x) {
    const v = this.d.read(this.n);
    const y = -this.g * x + v;
    this.d.write(x + this.g * y);
    return y;
  }
}

/**
 * Feedback delay network: four diffusing allpasses into eight damped delay
 * lines mixed by a Householder matrix. The delay lines are slowly modulated,
 * which is what stops a long tail from ringing on one metallic pitch.
 * `rt60` near 0.5 is a small plate for clicks; 6-8 is a hall for a bed.
 */
export class FDNReverb {
  constructor(sr, { rt60 = 6, damp = 4200, preDelay = 0.02, modDepth = 3.2, modRate = 0.07, seed = 7 } = {}) {
    this.sr = sr;
    const r = rng(seed);
    const base = [0.0297, 0.0371, 0.0411, 0.0437, 0.0532, 0.0611, 0.0693, 0.0771];
    this.lines = base.map((sec, i) => {
      const n = Math.round(sec * sr * (0.94 + r() * 0.12));
      return {
        d: new Delay(n + 512),
        n,
        // Per-line gain for the target RT60: g = 10^(-3 * lineTime / rt60).
        g: Math.pow(10, (-3 * (n / sr)) / rt60),
        lp: new OnePole(sr, damp * (0.75 + 0.5 * ((i + 1) / 8))),
        phase: r(),
        rate: modRate * (0.6 + r() * 0.9),
      };
    });
    this.diffusion = [
      new Allpass(Math.round(0.0043 * sr), 0.72),
      new Allpass(Math.round(0.0071 * sr), 0.7),
      new Allpass(Math.round(0.0113 * sr), 0.63),
      new Allpass(Math.round(0.0167 * sr), 0.6),
    ];
    this.pre = new Delay(Math.round(preDelay * sr) + 8);
    this.preN = Math.max(1, Math.round(preDelay * sr));
    this.modDepth = modDepth;
    this.dc = [new DCBlock(), new DCBlock()];
    this.t = 0;
    // Scratch for one step, so the inner loop allocates nothing.
    this.taps = new Float64Array(8);
    this.pair = [0, 0];
  }
  /** One mono sample in, one stereo pair out (the same array, reused). */
  run(x) {
    this.pre.write(x);
    let v = this.pre.read(this.preN);
    for (const ap of this.diffusion) v = ap.run(v);

    const out = this.taps;
    let sum = 0;
    for (let i = 0; i < 8; i++) {
      const L = this.lines[i];
      const mod = Math.sin(TAU * (L.phase + L.rate * this.t)) * this.modDepth;
      out[i] = L.lp.lp(L.d.read(L.n + mod)) * L.g;
      sum += out[i];
    }
    // Householder: y = x - (2/N) * sum(x). Lossless, maximally diffusing.
    const corr = (2 / 8) * sum;
    for (let i = 0; i < 8; i++) this.lines[i].d.write(v + (out[i] - corr));

    this.t += 1 / this.sr;
    // Split the lines across the field rather than summing then panning.
    this.pair[0] = this.dc[0].run(out[0] + out[2] - out[5] + out[7]) * 0.32;
    this.pair[1] = this.dc[1].run(out[1] - out[3] + out[4] + out[6]) * 0.32;
    return this.pair;
  }
}

// ── Envelopes ──────────────────────────────────────────────────────────
/**
 * Vactrol-ish lowpass gate response: a fast attack into a two-stage decay that
 * starts quickly and then hangs on. A plain exponential reads as a synth blip.
 */
export function lpgEnv(t, decay) {
  if (t < 0) return 0;
  const attack = 0.004;
  if (t < attack) return t / attack;
  const u = (t - attack) / decay;
  return Math.exp(-u * 3.1) * (0.72 + 0.28 * Math.exp(-u * 0.55));
}

/** Percussive AD with a shaped curve. `shape` > 1 decays faster up front. */
export function adEnv(t, attack, decay, shape = 1) {
  if (t < 0) return 0;
  if (t < attack) return Math.pow(t / attack, 0.6);
  return Math.exp(-Math.pow((t - attack) / decay, shape) * 3.2);
}

/** Symmetric swell, for entries that have no transient. */
export function swellEnv(t, dur, skew = 0.42) {
  if (t < 0 || t > dur) return 0;
  const u = t / dur;
  const p = u < skew ? u / skew : 1 - (u - skew) / (1 - skew);
  return Math.sin(clamp(p, 0, 1) * Math.PI * 0.5) ** 1.4;
}

export const softClip = (x) => Math.tanh(x * 1.18) * 0.86;

// ── Wavetables ─────────────────────────────────────────────────────────
/**
 * Single-cycle wavetable. Summing harmonics per sample for a dozen detuned
 * oscillators over a whole take costs minutes; summing them once into a table
 * and reading it back costs nothing.
 */
export class Wavetable {
  constructor(build, size = 4096) {
    this.size = size;
    this.t = new Float64Array(size);
    for (let i = 0; i < size; i++) this.t[i] = build(i / size);
  }
  read(phase) {
    const p = (phase - Math.floor(phase)) * this.size;
    const i = p | 0;
    const f = p - i;
    return this.t[i] * (1 - f) + this.t[(i + 1) % this.size] * f;
  }
}

/** Saw with `n` harmonics: soft enough at n=20 to sit under a filter. */
export const sawTable = (n = 20) =>
  new Wavetable((u) => {
    let s = 0;
    for (let k = 1; k <= n; k++) s += Math.sin(TAU * u * k) / k;
    return s * 0.55;
  });

/** Odd harmonics at 1/k²: hollow, clarinet-ish. */
export const hollowTable = (n = 13) =>
  new Wavetable((u) => {
    let s = 0;
    for (let k = 1; k <= n; k += 2) s += Math.sin(TAU * u * k) / (k * k);
    return s * 1.1;
  });

/** Triangle: odd harmonics at 1/k² with alternating sign, band-limited at `n`. */
export const triangleTable = (n = 15) =>
  new Wavetable((u) => {
    let s = 0;
    for (let k = 1; k <= n; k += 2) {
      const sign = ((k - 1) / 2) % 2 === 0 ? 1 : -1;
      s += (sign * Math.sin(TAU * u * k)) / (k * k);
    }
    return s * (8 / (Math.PI * Math.PI));
  });

// ── Buses ──────────────────────────────────────────────────────────────
/**
 * A stereo pair with two effect sends, written to sample by sample with an
 * equal-power pan. Out-of-range writes are dropped, so a voice that runs past
 * the end of the take needs no bounds check of its own.
 * @param {number} sr @param {number} n samples
 */
export function makeBus(sr, n) {
  return {
    sr,
    n,
    L: new Float64Array(n),
    R: new Float64Array(n),
    sendA: new Float64Array(n),
    sendB: new Float64Array(n),
    add(i, x, pan = 0, a = 0, b = 0) {
      if (i < 0 || i >= n) return;
      const p = (clamp(pan, -1, 1) + 1) * (Math.PI / 4);
      this.L[i] += x * Math.cos(p);
      this.R[i] += x * Math.sin(p);
      if (a) this.sendA[i] += x * a;
      if (b) this.sendB[i] += x * b;
    },
  };
}
