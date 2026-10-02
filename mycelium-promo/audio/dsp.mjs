// Signal primitives for the promo's backing track. Everything here is
// sample-rate agnostic and allocation-free in the inner loop; the score
// (score.mjs) drives it.

export const TAU = Math.PI * 2;

/** Seeded PRNG. The score never calls Math.random, so a render is reproducible. */
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

/** 12-TET from A4=440. Note names as "D2", "F#3", "Bb4". */
const SEMITONES = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
export function hz(note) {
  const m = /^([A-G])([#b]?)(-?\d+)$/.exec(note);
  if (!m) throw new Error(`bad note: ${note}`);
  const semi = SEMITONES[m[1]] + (m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0);
  const midi = (Number(m[3]) + 1) * 12 + semi;
  return 440 * Math.pow(2, (midi - 69) / 12);
}

// ── Filters ────────────────────────────────────────────────────────────
export class OnePole {
  constructor(sr, cutoff) { this.sr = sr; this.z = 0; this.setCutoff(cutoff); }
  setCutoff(f) { this.a = Math.exp((-TAU * clamp(f, 1, this.sr * 0.49)) / this.sr); }
  lp(x) { this.z = x + this.a * (this.z - x); return this.z; }
  hp(x) { return x - this.lp(x); }
}

/**
 * Topology-preserving state-variable filter (Zavalishin). Stable when the
 * cutoff is swept every sample, which the pad and the lowpass gates both do.
 */
export class SVF {
  constructor(sr) { this.sr = sr; this.ic1 = 0; this.ic2 = 0; this.g = 0; this.k = 1; }
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
    return { lp: v2, bp: v1, hp: x - k * v1 - v2 };
  }
  lp(x, cutoff, q) { this.set(cutoff, q); return this.run(x).lp; }
  bp(x, cutoff, q) { this.set(cutoff, q); return this.run(x).bp; }
}

export class DCBlock {
  constructor() { this.x1 = 0; this.y1 = 0; }
  run(x) { const y = x - this.x1 + 0.9985 * this.y1; this.x1 = x; this.y1 = y; return y; }
}

/** Voss-McCartney pink noise — the substrate hiss, without white's top-end bite. */
export class PinkNoise {
  constructor(rand) { this.rand = rand; this.rows = new Float64Array(7); this.running = 0; this.counter = 0; }
  next() {
    const r = this.rand;
    this.counter = (this.counter + 1) >>> 0;
    let n = this.counter;
    for (let i = 0; i < 7; i++) {
      if ((n & 1) === 0) { this.running -= this.rows[i]; this.rows[i] = r() * 2 - 1; this.running += this.rows[i]; break; }
      n >>>= 1;
    }
    return (this.running + (r() * 2 - 1)) * 0.16;
  }
}

// ── Delay / reverb ─────────────────────────────────────────────────────
export class Delay {
  constructor(maxSamples) { this.buf = new Float64Array(Math.max(4, Math.ceil(maxSamples))); this.w = 0; }
  write(x) { this.buf[this.w] = x; this.w = (this.w + 1) % this.buf.length; }
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
  constructor(samples, g) { this.d = new Delay(samples + 4); this.n = samples; this.g = g; }
  run(x) { const v = this.d.read(this.n); const y = -this.g * x + v; this.d.write(x + this.g * y); return y; }
}

/**
 * Feedback delay network: four diffusing allpasses into eight damped delay
 * lines mixed by a Householder matrix. The delay lines are slowly modulated,
 * which is what stops a long tail from ringing on one metallic pitch — the
 * difference between "ambient" and "a reverb preset".
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
  }
  /** One mono sample in, one stereo pair out. */
  run(x) {
    this.pre.write(x);
    let v = this.pre.read(this.preN);
    for (const ap of this.diffusion) v = ap.run(v);

    const N = 8;
    const out = new Array(N);
    let sum = 0;
    for (let i = 0; i < N; i++) {
      const L = this.lines[i];
      const mod = Math.sin(TAU * (L.phase + L.rate * this.t)) * this.modDepth;
      out[i] = L.lp.lp(L.d.read(L.n + mod)) * L.g;
      sum += out[i];
    }
    // Householder: y = x - (2/N) * sum(x). Lossless, maximally diffusing.
    const corr = (2 / N) * sum;
    for (let i = 0; i < N; i++) this.lines[i].d.write(v + (out[i] - corr));

    this.t += 1 / this.sr;
    // Split the lines across the field rather than summing then panning.
    const l = out[0] + out[2] - out[5] + out[7];
    const rr = out[1] - out[3] + out[4] + out[6];
    return [this.dc[0].run(l) * 0.32, this.dc[1].run(rr) * 0.32];
  }
}

// ── Envelopes / voices ─────────────────────────────────────────────────
/**
 * Vactrol-ish lowpass gate response: a fast attack into a two-stage decay
 * that starts quickly and then hangs on. This lag is the whole character of
 * a Buchla-style gate — a plain exponential reads as a synth blip instead.
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

/** Symmetric swell — for pad entries and risers that have no transient. */
export function swellEnv(t, dur, skew = 0.42) {
  if (t < 0 || t > dur) return 0;
  const u = t / dur;
  const p = u < skew ? u / skew : 1 - (u - skew) / (1 - skew);
  return Math.sin(clamp(p, 0, 1) * Math.PI * 0.5) ** 1.4;
}

export const softClip = (x) => Math.tanh(x * 1.18) * 0.86;

// ── WAV ────────────────────────────────────────────────────────────────
export function encodeWav(left, right, sr) {
  const frames = left.length;
  const bytes = frames * 4;
  const buf = Buffer.alloc(44 + bytes);
  buf.write('RIFF', 0);
  buf.writeUInt32LE(36 + bytes, 4);
  buf.write('WAVE', 8);
  buf.write('fmt ', 12);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(2, 22);
  buf.writeUInt32LE(sr, 24);
  buf.writeUInt32LE(sr * 4, 28);
  buf.writeUInt16LE(4, 32);
  buf.writeUInt16LE(16, 34);
  buf.write('data', 36);
  buf.writeUInt32LE(bytes, 40);
  for (let i = 0; i < frames; i++) {
    buf.writeInt16LE(Math.round(clamp(left[i], -1, 1) * 32767), 44 + i * 4);
    buf.writeInt16LE(Math.round(clamp(right[i], -1, 1) * 32767), 46 + i * 4);
  }
  return buf;
}

/**
 * Single-cycle wavetable. The pad stacks a dozen detuned oscillators over the
 * whole 107 seconds; summing harmonics per sample for each of them costs
 * minutes, so the harmonics are summed once into a table and read back.
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

/** Saw with `n` harmonics — soft enough at n=20 to sit under a filter. */
export const sawTable = (n = 20) =>
  new Wavetable((u) => {
    let s = 0;
    for (let k = 1; k <= n; k++) s += Math.sin(TAU * u * k) / k;
    return s * 0.55;
  });

/** Odd harmonics only: hollow, clarinet-ish. The pad's inner voice. */
export const hollowTable = (n = 13) =>
  new Wavetable((u) => {
    let s = 0;
    for (let k = 1; k <= n; k += 2) s += Math.sin(TAU * u * k) / (k * k);
    return s * 1.1;
  });

/**
 * Triangle: odd harmonics rolling off at 1/k² with alternating sign. Far softer
 * than the FM bell — no bright inharmonic partials, so it reads as a mallet or
 * a bloom rather than a plucked tine. Band-limited by construction (the sum
 * stops at `n`), so it stays clean under the lowpass gate.
 */
export const triangleTable = (n = 15) =>
  new Wavetable((u) => {
    let s = 0;
    for (let k = 1; k <= n; k += 2) {
      const sign = ((k - 1) / 2) % 2 === 0 ? 1 : -1;
      s += (sign * Math.sin(TAU * u * k)) / (k * k);
    }
    return s * (8 / (Math.PI * Math.PI));
  });
