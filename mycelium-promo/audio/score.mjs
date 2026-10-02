// The demo's sound: a gentle drone under the whole take, and the clicks and
// keystrokes of the person driving it, placed where they land in the picture.
//
// The drone is the old promo score's bed alone: sine partials on a D chord
// that breathe on their own slow LFOs, pink-noise "soil" through a slowly
// moving bandpass, a dark pad, and a sub swell every couple of beats. Nothing
// in it is plucked or bright; it sits under the video rather than scoring it.
//
// The clicks and keys come from the recorder (`<video>.sounds.json`, written by
// shotkit beside a staged take): a soft low "tock" per click, and a quiet tick
// per character, spread over the span a string was typed in.

import {
  FDNReverb, OnePole, PinkNoise, SVF, DCBlock, TAU,
  clamp, hz, rng, hollowTable, softClip, swellEnv,
} from './dsp.mjs';
import { glue, limit, lra, lufs, truePeakDb } from './master.mjs';

/** Where the drone sits, before the clicks go on top: a bed, not a score. */
const BED_LUFS = -23.0;
/** The drone's level under the clicks once the mix is set, so turning the
 *  drone down leaves the clicks and keys where they are. */
const BED_TRIM_DB = -6.0;
/** The finished track, clicks included. */
export const TARGET_LUFS = -19.0;

const BEAT = 0.8625;

// Bare D and A to open, D minor (the third, F, quietly) for the body, and bare
// again an octave wider to close. `bright` caps the pad's filter, low throughout.
function sections(duration) {
  const outro = Math.max(10, duration - 6);
  return [
    { t0: 0, t1: 6, gain: 0.7, bright: 0.3, chord: ['D2', 'A2', 'D3'] },
    { t0: 6, t1: outro, gain: 0.9, bright: 0.42, chord: ['D2', 'A2', 'F3', 'A3'] },
    { t0: outro, t1: duration, gain: 0.75, bright: 0.3, chord: ['D2', 'A2', 'D3', 'A3'] },
  ];
}

function makeBuses(sr, n) {
  return {
    sr, n,
    L: new Float64Array(n), R: new Float64Array(n),
    hall: new Float64Array(n), plate: new Float64Array(n),
    add(i, x, pan = 0, sendHall = 0, sendPlate = 0) {
      if (i < 0 || i >= n) return;
      const a = (clamp(pan, -1, 1) + 1) * (Math.PI / 4);
      this.L[i] += x * Math.cos(a);
      this.R[i] += x * Math.sin(a);
      if (sendHall) this.hall[i] += x * sendHall;
      if (sendPlate) this.plate[i] += x * sendPlate;
    },
  };
}

const idx = (b, t) => Math.round(t * b.sr);

/** Sine partials per chord tone, each on its own slow LFO, so it never repeats. */
function renderSubstrate(b, secs, duration) {
  const r = rng(0x5eed01);
  const dt = 1 / b.sr;
  for (const sec of secs) {
    for (const [ci, note] of sec.chord.entries()) {
      const f = hz(note);
      for (let k = 0; k < 3; k++) {
        const v = {
          f: f * (1 + (r() - 0.5) * 0.004) * (k === 2 ? 2 : 1),
          amp: (k === 2 ? 0.16 : 0.42) / (1 + ci * 0.45),
          phase: r(),
          lfoRate: 0.021 + r() * 0.083,
          lfoPhase: r(),
          lfoDepth: 0.3 + r() * 0.45,
          pan: (r() * 2 - 1) * 0.72,
          panRate: 0.013 + r() * 0.024,
        };
        const t0 = Math.max(0, sec.t0 - 2.2);
        const t1 = Math.min(duration, sec.t1 + 2.6);
        let ph = v.phase;
        const lp = new OnePole(b.sr, 900);
        for (let i = idx(b, t0); i < idx(b, t1); i++) {
          const t = i / b.sr;
          const fade = Math.min(1, (t - t0) / 2.6) * Math.min(1, (t1 - t) / 3.0);
          if (fade > 0) {
            const lfo = 1 - v.lfoDepth * 0.5 * (1 - Math.cos(TAU * (v.lfoPhase + v.lfoRate * t)));
            const s = lp.lp(Math.sin(TAU * ph)) * v.amp * lfo * fade * sec.gain;
            b.add(i, s * 0.055, v.pan * Math.cos(TAU * (v.panRate * t + v.lfoPhase)), 0.5, 0);
          }
          ph += v.f * dt;
        }
      }
    }
  }
}

/** Pink noise through a bandpass that breathes, kept low and soft. */
function renderSoil(b, secs) {
  const pink = new PinkNoise(rng(0xa11ce));
  const svf = new SVF(b.sr);
  const hp = new OnePole(b.sr, 90);
  for (let i = 0; i < b.n; i++) {
    const t = i / b.sr;
    const sec = secs.find((s) => t >= s.t0 && t < s.t1) ?? secs[secs.length - 1];
    const sweep = 240 + 520 * sec.bright + 140 * Math.sin(TAU * 0.037 * t) + 90 * Math.sin(TAU * 0.0113 * t + 1.7);
    const s = svf.bp(hp.hp(pink.next()), sweep, 1.6) * 0.5;
    const env = 0.024 * sec.gain * (0.75 + 0.25 * Math.sin(TAU * 0.019 * t));
    b.add(i, s * env, Math.sin(TAU * 0.008 * t) * 0.5, 0.34, 0);
  }
}

/** The chord's upper tones as a hollow, darkly filtered pad. */
function renderPad(b, secs, duration) {
  const table = hollowTable(13);
  const r = rng(0xbadca11);
  const dt = 1 / b.sr;
  for (const sec of secs) {
    const t0 = Math.max(0, sec.t0 - 1.8);
    const t1 = Math.min(duration, sec.t1 + 2.4);
    for (const [ci, note] of sec.chord.entries()) {
      if (ci === 0) continue;
      const base = hz(note);
      const detunes = [-0.055, 0.0, 0.062].map((c) => base * Math.pow(2, c / 12));
      const phases = detunes.map(() => r());
      const pan = (r() * 2 - 1) * 0.8;
      const panRate = 0.017 + r() * 0.03;
      const svf = new SVF(b.sr);
      const amp = 0.026 / (1 + ci * 0.3);
      for (let i = idx(b, t0); i < idx(b, t1); i++) {
        const t = i / b.sr;
        const fade = Math.min(1, (t - t0) / 2.4) * Math.min(1, (t1 - t) / 2.8);
        let s = 0;
        for (let k = 0; k < 3; k++) {
          s += table.read(phases[k]) * (k === 1 ? 1 : 0.62);
          phases[k] += detunes[k] * dt;
        }
        if (fade <= 0) continue;
        // Dark on purpose: the cutoff never opens past ~1.4kHz.
        const cutoff = base * (1.6 + 3.0 * sec.bright) * (1 + 0.22 * Math.sin(TAU * (0.031 + ci * 0.007) * t));
        const y = svf.lp(s * 0.33, clamp(cutoff, 120, 1400), 0.9);
        b.add(i, y * amp * fade * sec.gain, pan * Math.cos(TAU * panRate * t), 0.62, 0.04);
      }
    }
  }
}

/** A sub swell every two beats once the room is up: felt more than heard. */
function renderThrob(b, secs, duration) {
  const period = BEAT * 2;
  const f = hz('D1');
  for (let t = 6; t < duration - 4; t += period) {
    const sec = secs.find((s) => t >= s.t0 && t < s.t1) ?? secs[secs.length - 1];
    const dur = period * 1.4;
    const i0 = idx(b, t);
    const i1 = Math.min(b.n, idx(b, t + dur));
    for (let i = i0; i < i1; i++) {
      const u = (i - i0) / b.sr;
      const s = Math.sin(TAU * f * u) + 0.28 * Math.sin(TAU * f * 2 * u);
      b.add(i, s * swellEnv(u, dur, 0.3) * 0.045 * sec.gain, 0, 0.12, 0);
    }
  }
}

// ── the person driving it ───────────────────────────────────────────────
// Written straight into a dry pair plus a short plate, after the bed is
// leveled, so a click is the same size wherever it falls.

/** A soft, low "tock": a pitched body that falls a little, under a short tap. */
function tock(out, sr, t, r, gain = 1) {
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
    const tap = svf.bp((r() * 2 - 1), 1900, 1.8) * Math.exp(-u * 600);
    out.add(i0 + k, (body * 0.9 + tap * 0.5) * 0.11 * gain, pan, 0.18);
  }
}

/** One key: a short, dark tick, a little different every time. */
function tick(out, sr, t, r, gain = 1) {
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
    out.add(i0 + k, (click * 0.65 + thump * 0.35) * 0.065 * g, pan, 0.12);
  }
}

function renderPerson(out, sr, events) {
  const r = rng(0xc11c);
  for (const e of events) {
    if (e.kind === 'click') tock(out, sr, e.t, r);
    else if (e.kind === 'key') tick(out, sr, e.t, r, 2.4);
    else if (e.kind === 'type' && e.chars > 0) {
      const t1 = typeof e.t1 === 'number' && e.t1 > e.t ? e.t1 : e.t + e.chars * 0.055;
      const step = (t1 - e.t) / e.chars;
      for (let c = 0; c < e.chars; c++) {
        // A little unevenness, as a hand types.
        tick(out, sr, e.t + c * step + (r() - 0.5) * step * 0.35, r);
      }
    }
  }
}

/**
 * Render the track for a video `duration` seconds long, with `events` from its
 * `.sounds.json`.
 */
export function render(duration, events, sr = 48000, { onProgress = () => {} } = {}) {
  const n = Math.ceil(duration * sr);
  const secs = sections(duration);
  const b = makeBuses(sr, n);
  for (const [name, fn] of [['substrate', renderSubstrate], ['soil', renderSoil], ['pad', renderPad], ['throb', renderThrob]]) {
    onProgress(name);
    fn(b, secs, duration);
  }

  onProgress('reverb');
  const hall = new FDNReverb(sr, { rt60: 7.2, damp: 3600, preDelay: 0.032, modDepth: 3.4, modRate: 0.061, seed: 11 });
  const L = new Float64Array(n);
  const R = new Float64Array(n);
  const dcL = new DCBlock();
  const dcR = new DCBlock();
  const hpL = new OnePole(sr, 26);
  const hpR = new OnePole(sr, 26);
  const lpL = new OnePole(sr, 9000);
  const lpR = new OnePole(sr, 9000);
  for (let i = 0; i < n; i++) {
    const [hl, hr] = hall.run(b.hall[i]);
    L[i] = softClip(lpL.lp(hpL.hp(dcL.run(b.L[i] + hl * 0.9))));
    R[i] = softClip(lpR.lp(hpR.hp(dcR.run(b.R[i] + hr * 0.9))));
  }
  glue(L, R, sr);
  const bed = Math.pow(10, (BED_LUFS - lufs(L, R, sr)) / 20);
  for (let i = 0; i < n; i++) { L[i] *= bed; R[i] *= bed; }

  onProgress('clicks and keys');
  const p = makeBuses(sr, n);
  renderPerson(p, sr, events);
  const plate = new FDNReverb(sr, { rt60: 0.6, damp: 5200, preDelay: 0.006, modDepth: 0.6, modRate: 0.21, seed: 29 });
  const pL = new Float64Array(n);
  const pR = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const [pl, pr] = plate.run(p.plate[i]);
    pL[i] = p.L[i] + pl * 0.5;
    pR[i] = p.R[i] + pr * 0.5;
  }

  onProgress('master');
  // The overall gain is set on the mix at the bed's reference level; the trim
  // comes after, so it moves the drone alone.
  const refL = L.map((x, i) => x + pL[i]);
  const refR = R.map((x, i) => x + pR[i]);
  const gain = Math.pow(10, (TARGET_LUFS - lufs(refL, refR, sr)) / 20);
  const trim = Math.pow(10, BED_TRIM_DB / 20);
  for (let i = 0; i < n; i++) {
    L[i] = (L[i] * trim + pL[i]) * gain;
    R[i] = (R[i] * trim + pR[i]) * gain;
  }
  const lim = limit(L, R, sr, { ceiling: 0.8 });
  const FADE_IN = 0.35;
  const FADE_OUT = 2.6;
  for (let i = 0; i < n; i++) {
    const t = i / sr;
    const f = Math.min(1, t / FADE_IN) * Math.min(1, Math.max(0, (duration - t) / FADE_OUT));
    L[i] *= f;
    R[i] *= f;
  }
  return {
    left: L, right: R, sampleRate: sr,
    lufs: lufs(L, R, sr), lra: lra(L, R, sr), truePeakDb: truePeakDb(L, R),
    limiterReductionDb: lim.maxGainReductionDb,
  };
}
