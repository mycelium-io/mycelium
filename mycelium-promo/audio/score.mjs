// The backing track for index.html, written against that file's timeline.
//
// The piece is one continuous organism rather than nine cues stitched
// together: a drone bed and a noise substrate run unbroken for all 107
// seconds, and everything else grows out of them. Two things move it —
//
//   the SECTIONS table, whose harmony follows the video's argument, and
//   the CUES table, whose times are read straight out of index.html's GSAP
//   calls, so a motif lands on the frame that earns it.
//
// The through-line is the third of the chord. Through the negotiation the
// chord has no third at all, and two voices supply competing ones a semitone
// apart: @rowan lands on F, @avery on F#. At 81.4s — the frame where the
// offer table locks green — rowan's figure takes F# instead, a sustained
// voice glides the semitone under it, and the harmony resolves to D–F#–A–E.
// The disagreement and its resolution are the same note.

import {
  FDNReverb, OnePole, PinkNoise, SVF, DCBlock, TAU,
  adEnv, clamp, hz, lerp, lpgEnv, rng, sawTable, hollowTable, triangleTable,
  softClip, swellEnv,
} from './dsp.mjs';
import { glue, limit, lra, lufs, truePeakDb } from './master.mjs';

export const DURATION = 107;

// ~69.6 BPM. index.html's scene changes land on multiples of 6.9s (13.8,
// 27.6, 41.4), so an eight-beat phrase lines up with the cut without the
// generative layers ever having to be quantised to it.
const BEAT = 0.8625;
const STEP = BEAT / 2;

// ── Harmony ────────────────────────────────────────────────────────────
// t0/t1 are the video's own scene boundaries. `chord` is the harmony every
// layer draws from: the drone bed voices it, and the generative hyphae picks
// and snaps to its tones (voiced up an octave or two, see chordVoicing).
// `density` is the hyphae's probability per step.
const SECTIONS = [
  { id: 'emergence', t0: 0.0, t1: 13.8, gain: 0.70, bright: 0.45,
    chord: ['D2', 'A2', 'D3'], density: 0.10 },

  { id: 'substrate', t0: 13.8, t1: 27.6, gain: 0.80, bright: 0.55,
    chord: ['D2', 'A2', 'D3', 'C4'], density: 0.20 },

  { id: 'room', t0: 27.6, t1: 41.4, gain: 0.86, bright: 0.66,
    chord: ['D2', 'A2', 'D3', 'G3', 'C4'], density: 0.28 },

  { id: 'agents', t0: 41.4, t1: 52.2, gain: 0.92, bright: 0.72,
    chord: ['D2', 'A2', 'F3', 'C4', 'D4'], density: 0.26 },

  { id: 'mention', t0: 52.2, t1: 61.6, gain: 0.9, bright: 0.7,
    chord: ['D2', 'A2', 'F3', 'C4', 'E4'], density: 0.24 },

  // No third anywhere in the chord: the question the agents are arguing
  // about is exactly the note the harmony refuses to name.
  { id: 'negotiate', t0: 61.6, t1: 81.4, gain: 0.80, bright: 0.6,
    chord: ['D2', 'A2', 'D3', 'G3', 'E4'], density: 0.15 },

  // Consensus. F# arrives and stays.
  { id: 'consensus', t0: 81.4, t1: 94.4, gain: 1.0, bright: 0.86,
    chord: ['D2', 'A2', 'F#3', 'A3', 'E4'], density: 0.40 },

  { id: 'distill', t0: 94.4, t1: 100.4, gain: 0.78, bright: 0.8,
    chord: ['D2', 'A2', 'E4', 'A4'], density: 0.18 },

  { id: 'outro', t0: 100.4, t1: 107.0, gain: 0.95, bright: 0.7,
    chord: ['D1', 'D2', 'A2', 'D3', 'A3', 'D4'], density: 0.10 },
];

const sectionAt = (t) => SECTIONS.find((s) => t >= s.t0 && t < s.t1) ?? SECTIONS[SECTIONS.length - 1];

// ── Cues ───────────────────────────────────────────────────────────────
// Every time below is a GSAP position in index.html. Grouped by scene so a
// change to the animation can be traced to the motif that follows it.
const line = (t, pitch, gain = 0.14) => ({ t, kind: 'tick', pitch, gain });

const CUES = [
  // Scene 1 · hero (0–7). The spore: one bell, and a long way down.
  { t: 0.55, kind: 'spore', pitch: 'D5', gain: 0.15 },
  { t: 1.05, kind: 'spore', pitch: 'A5', gain: 0.07 },

  // Scene 2 · install the CLI (6.6–14.6). Eight lines at 0.55s.
  { t: 6.6, kind: 'lift', gain: 0.3 },
  ...['D5', 'A4', 'D5', 'F5', 'C5', 'D5', 'F5', 'A5'].map((p, i) =>
    line(7.6 + i * 0.55, p, i === 7 ? 0.26 : 0.12)),
  { t: 11.45, kind: 'bloom', pitch: 'D5', gain: 0.11 }, // "Installation complete!"

  // Scene 3 · bring up the stack (13.8–27.8). Services report in.
  { t: 13.8, kind: 'lift', gain: 0.34 },
  line(14.7, 'D5'), line(15.2, 'F5'), line(15.8, 'C5'),
  line(16.2, 'A4', 0.09), line(16.6, 'A4', 0.09),
  line(17.4, 'G4', 0.1),
  // Three containers come up healthy: a rising figure, one per service.
  { t: 18.1, kind: 'pluck', pitch: 'D4', gain: 0.2, decay: 1.6 },
  { t: 18.7, kind: 'pluck', pitch: 'F4', gain: 0.2, decay: 1.6 },
  line(19.3, 'C5', 0.1),
  { t: 19.9, kind: 'pluck', pitch: 'A4', gain: 0.22, decay: 1.8 },
  { t: 20.8, kind: 'bloom', pitch: 'D5', gain: 0.26 }, // "Mycelium is ready."

  // Scene 4 · create a room (27.6–41.6).
  { t: 27.6, kind: 'lift', gain: 0.34 },
  line(28.6, 'D5'), line(29.2, 'G4', 0.1),
  line(29.9, 'D5'), line(30.5, 'G4', 0.1),
  line(31.2, 'C5'),
  { t: 32.0, kind: 'pluck', pitch: 'D5', gain: 0.24, decay: 2.2 }, // memory written
  // The workspace slides up over the terminal — the one big move in the act.
  { t: 35.0, kind: 'impact', gain: 0.42 },
  { t: 36.3, kind: 'pluck', pitch: 'A4', gain: 0.13, decay: 1.4 },
  { t: 36.5, kind: 'pluck', pitch: 'C5', gain: 0.12, decay: 1.4 },
  { t: 36.9, kind: 'pluck', pitch: 'D5', gain: 0.13, decay: 1.6 },
  { t: 37.2, kind: 'pluck', pitch: 'G5', gain: 0.1, decay: 1.3 },

  // Scene 5 · wire up the agents (41.4–52.4). Three registrations stack a
  // triad: the room acquires its citizens.
  { t: 41.4, kind: 'lift', gain: 0.34 },
  line(42.4, 'D5'),
  { t: 43.1, kind: 'voice', pitch: 'F4', gain: 0.38, decay: 3.0 }, // @avery-agent
  line(43.8, 'D5'),
  { t: 44.5, kind: 'voice', pitch: 'A4', gain: 0.4, decay: 3.0 }, // @rowan-agent
  line(45.2, 'D5'),
  { t: 45.9, kind: 'voice', pitch: 'C5', gain: 0.44, decay: 3.6 }, // @aligner
  line(46.6, 'F5', 0.1),

  // Scene 5b · @-mention from the room (52.2–62.0).
  { t: 52.2, kind: 'lift', gain: 0.3 },
  { t: 53.6, kind: 'pluck', pitch: 'D5', gain: 0.22, decay: 2.0 }, // alex posts
  { t: 56.6, kind: 'zoom', dur: 0.9, gain: 0.32 },                 // camera pushes in
  // "avery-agent is thinking…" — three dots, three taps.
  { t: 58.25, kind: 'tick', pitch: 'A5', gain: 0.08 },
  { t: 58.5, kind: 'tick', pitch: 'A5', gain: 0.08 },
  { t: 58.75, kind: 'tick', pitch: 'A5', gain: 0.08 },
  { t: 59.1, kind: 'pluck', pitch: 'F5', gain: 0.24, decay: 2.4 }, // the reply lands

  // Scene 6 · the negotiation (61.6–85.6). Round markers, moves, consensus.
  { t: 61.6, kind: 'lift', gain: 0.3 },
  { t: 66.5, kind: 'zoom', dur: 0.9, gain: 0.28 },
  ...[65.3, 68.9, 72.3, 75.6, 78.6].map((t, i) =>
    ({ t, kind: 'round', gain: 0.44 + i * 0.055 })),
  // avery proposes / counters — the higher voice.
  ...[[67.0, 'A4'], [70.5, 'B4'], [77.1, 'C5']].map(([t, pitch]) =>
    ({ t, kind: 'move', pitch, gain: 0.26, actor: 'avery' })),
  // rowan counters — the lower voice.
  ...[[73.85, 'D4'], [77.8, 'F4']].map(([t, pitch]) =>
    ({ t, kind: 'move', pitch, gain: 0.26, actor: 'rowan' })),
  // Rejections: the same gesture, bent flat and damped short.
  ...[[67.8, 'rowan'], [71.3, 'rowan'], [74.65, 'avery']].map(([t, actor]) =>
    ({ t, kind: 'reject', gain: 0.44, actor })),
  // Both accept.
  { t: 79.9, kind: 'accept', pitch: 'D5', gain: 0.2, actor: 'avery' },
  { t: 80.6, kind: 'accept', pitch: 'A5', gain: 0.2, actor: 'rowan' },
  // Consensus. The offer table locks green at 81.4 and the piece turns major.
  { t: 81.4, kind: 'consensus', gain: 1.05 },
  { t: 82.4, kind: 'bloom', pitch: 'F#5', gain: 0.3 },

  // Scene 6b · the plan (85.4–94.4). Four tasks compile, two get done.
  { t: 85.4, kind: 'lift', gain: 0.34 },
  ...['D5', 'F#5', 'A5', 'B5'].map((p, i) =>
    ({ t: 87.9 + i * 0.45, kind: 'pluck', pitch: p, gain: 0.19, decay: 1.9 })),
  { t: 91.38, kind: 'done', pitch: 'D6', gain: 0.3 },
  { t: 92.48, kind: 'done', pitch: 'F#6', gain: 0.3 },

  // Scene 6c · the synthesizer distils the room (94.4–100.4).
  { t: 94.4, kind: 'lift', gain: 0.28 },
  ...['A5', 'E5', 'D5', 'A4'].map((p, i) =>
    ({ t: 96.8 + i * 0.4, kind: 'pluck', pitch: p, gain: 0.16, decay: 2.6 })),
  { t: 98.4, kind: 'spore', pitch: 'D6', gain: 0.2 }, // the memory lands

  // Scene 7 · outro (100.4–106.4). The bell from 0.55s comes back an octave
  // down and twice as wide: the spore has fruited.
  { t: 100.6, kind: 'spore', pitch: 'D4', gain: 0.22 },
  { t: 100.62, kind: 'impact', gain: 0.34 },
  { t: 101.2, kind: 'spore', pitch: 'A4', gain: 0.1 },
  { t: 101.8, kind: 'spore', pitch: 'D5', gain: 0.08 },
];

// ── Buses ──────────────────────────────────────────────────────────────
// Two reverbs. `hall` is the room the whole piece sits in — a seven-second
// tail that never quite clears, so the drone bed reads as one continuous
// space. `plate` is short and is what makes a pluck sound played rather
// than pasted in.
function makeBuses(sr, n) {
  return {
    sr, n,
    L: new Float64Array(n), R: new Float64Array(n),
    hall: new Float64Array(n), plate: new Float64Array(n),
    /** Constant-power pan into the dry pair plus the two sends. */
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

// ── Sustained layers ───────────────────────────────────────────────────
/**
 * The drone bed. Every chord tone gets three partials, each with its own
 * amplitude LFO at a rate that shares no common factor with the others, so
 * the bed's texture never lands in the same place twice across 107 seconds.
 */
function renderSubstrate(b) {
  const r = rng(0x5eed01);
  const voices = [];
  for (const sec of SECTIONS) {
    for (const [ci, note] of sec.chord.entries()) {
      const f = hz(note);
      for (let k = 0; k < 3; k++) {
        voices.push({
          sec, f: f * (1 + (r() - 0.5) * 0.004) * (k === 2 ? 2 : 1),
          amp: (k === 2 ? 0.16 : 0.42) / (1 + ci * 0.45),
          phase: r(),
          lfoRate: 0.021 + r() * 0.083, // irrational-ish spread, never in step
          lfoPhase: r(),
          lfoDepth: 0.3 + r() * 0.45,
          pan: (r() * 2 - 1) * 0.72,
          panRate: 0.013 + r() * 0.024,
        });
      }
    }
  }
  const dt = 1 / b.sr;
  for (const v of voices) {
    // Sections overlap by a couple of seconds so nothing switches on a cut.
    const t0 = Math.max(0, v.sec.t0 - 2.2);
    const t1 = Math.min(DURATION, v.sec.t1 + 2.6);
    const i0 = idx(b, t0);
    const i1 = idx(b, t1);
    let ph = v.phase;
    const lp = new OnePole(b.sr, 900);
    for (let i = i0; i < i1; i++) {
      const t = i / b.sr;
      const fade =
        Math.min(1, (t - t0) / 2.6) * Math.min(1, (t1 - t) / 3.0);
      if (fade <= 0) { ph += v.f * dt; continue; }
      const lfo = 1 - v.lfoDepth * 0.5 * (1 - Math.cos(TAU * (v.lfoPhase + v.lfoRate * t)));
      const s = lp.lp(Math.sin(TAU * ph)) * v.amp * lfo * fade * v.sec.gain;
      const pan = v.pan * Math.cos(TAU * (v.panRate * t + v.lfoPhase));
      b.add(i, s * 0.055, pan, 0.5, 0);
      ph += v.f * dt;
    }
  }
}

/** Damp earth: pink noise through a bandpass that breathes across the piece. */
function renderSoil(b) {
  const pink = new PinkNoise(rng(0xa11ce));
  const svf = new SVF(b.sr);
  const hp = new OnePole(b.sr, 90);
  for (let i = 0; i < b.n; i++) {
    const t = i / b.sr;
    const sec = sectionAt(t);
    const sweep = 260 + 900 * sec.bright
      + 190 * Math.sin(TAU * 0.037 * t) + 120 * Math.sin(TAU * 0.0113 * t + 1.7);
    const x = hp.hp(pink.next());
    const s = svf.bp(x, sweep, 1.6) * 0.5;
    const env = 0.028 * sec.gain * (0.75 + 0.25 * Math.sin(TAU * 0.019 * t));
    b.add(i, s * env, Math.sin(TAU * 0.008 * t) * 0.5, 0.34, 0);
  }
}

/**
 * The harmonic body: per section, each chord tone as three detuned
 * oscillators through a slowly-opening lowpass. `bright` is the section's
 * cutoff — the piece opens up as the video does.
 */
function renderPad(b) {
  const sawT = sawTable(18);
  const hollowT = hollowTable(13);
  const r = rng(0xbadca11);
  const dt = 1 / b.sr;
  for (const sec of SECTIONS) {
    const t0 = Math.max(0, sec.t0 - 1.8);
    const t1 = Math.min(DURATION, sec.t1 + 2.4);
    const i0 = idx(b, t0);
    const i1 = idx(b, t1);
    for (const [ci, note] of sec.chord.entries()) {
      if (ci === 0) continue; // the root is the substrate's job
      const base = hz(note);
      const detunes = [-0.055, 0.0, 0.062].map((c) => base * Math.pow(2, c / 12));
      const phases = detunes.map(() => r());
      const pan = (r() * 2 - 1) * 0.8;
      const panRate = 0.017 + r() * 0.03;
      const svf = new SVF(b.sr);
      const amp = 0.03 / (1 + ci * 0.3);
      const useHollow = ci % 2 === 0;
      for (let i = i0; i < i1; i++) {
        const t = i / b.sr;
        const fade = Math.min(1, (t - t0) / 2.4) * Math.min(1, (t1 - t) / 2.8);
        if (fade <= 0) { for (let k = 0; k < 3; k++) phases[k] += detunes[k] * dt; continue; }
        let s = 0;
        for (let k = 0; k < 3; k++) {
          s += (useHollow ? hollowT : sawT).read(phases[k]) * (k === 1 ? 1 : 0.62);
          phases[k] += detunes[k] * dt;
        }
        const cutoff = base * (2.0 + 5.0 * sec.bright)
          * (1 + 0.28 * Math.sin(TAU * (0.031 + ci * 0.007) * t));
        const y = svf.lp(s * 0.33, clamp(cutoff, 120, 7000), 1.1);
        b.add(i, y * amp * fade * sec.gain, pan * Math.cos(TAU * panRate * t), 0.62, 0.08);
      }
    }
  }
}

/**
 * Nutrient transport: a sub swell every two beats, at the octave under the
 * root. Felt more than heard, and the only thing in the piece keeping time.
 */
function renderThrob(b) {
  const period = BEAT * 2;
  for (let t = 13.8; t < 101.5; t += period) {
    const sec = sectionAt(t);
    const f = hz('D1');
    const dur = period * 1.4;
    const i0 = idx(b, t);
    const i1 = Math.min(b.n, idx(b, t + dur));
    // Louder once the room exists, quieter while the agents are arguing.
    const lvl = 0.055 * sec.gain * (sec.id === 'negotiate' ? 0.72 : 1)
      * (sec.id === 'consensus' ? 1.25 : 1);
    for (let i = i0; i < i1; i++) {
      const u = (i - i0) / b.sr;
      const env = swellEnv(u, dur, 0.3);
      const s = Math.sin(TAU * f * u) + 0.28 * Math.sin(TAU * f * 2 * u);
      b.add(i, s * env * lvl, 0, 0.12, 0);
    }
  }
}

// ── Plucked timbres ────────────────────────────────────────────────────
/**
 * Lowpass-gate pluck. Amplitude and cutoff fall together off one vactrol-ish
 * envelope, so a quiet note is also a dark one — the reason a Buchla-style
 * gate sounds struck rather than switched on. This is the piece's main voice.
 */
const TRI = triangleTable();
function pluckLPG(b, { t, freq, gain = 0.2, decay = 1.8, pan = 0, tone = 1, sendHall = 0.42, sendPlate = 0.3, wave = null }) {
  const i0 = idx(b, t);
  const len = Math.ceil(decay * 4.2 * b.sr);
  const svf = new SVF(b.sr);
  const dt = 1 / b.sr;
  let ph = 0;
  for (let k = 0; k < len; k++) {
    const i = i0 + k;
    if (i >= b.n) break;
    const u = k * dt;
    const env = lpgEnv(u, decay);
    if (env < 1e-5 && u > decay) break;
    // Default is a sine plus two partials; `wave` swaps in a wavetable (the
    // triangle) for a rounder, mallet-like body under the same gate.
    const s = wave
      ? wave.read(ph)
      : Math.sin(TAU * ph)
        + 0.34 * tone * Math.sin(TAU * ph * 2)
        + 0.13 * tone * Math.sin(TAU * ph * 3.01);
    const cutoff = freq * (1.4 + 7.5 * tone * env * env);
    const y = svf.lp(s * 0.5, clamp(cutoff, 60, 9000), 1.5);
    b.add(i, y * env * gain, pan, sendHall, sendPlate);
    ph += freq * dt;
  }
}

/** Two-operator FM bell. The spore at 0.55s, the memory ping, the check-offs. */
function pluckFM(b, { t, freq, gain = 0.25, decay = 2.6, ratio = 2.01, index = 4.2, pan = 0, sendHall = 0.6, sendPlate = 0.18 }) {
  const ATTACK = 0.003;
  const i0 = idx(b, t);
  const len = Math.ceil(decay * 4.5 * b.sr);
  const dt = 1 / b.sr;
  let ph = 0;
  let mph = 0;
  for (let k = 0; k < len; k++) {
    const i = i0 + k;
    if (i >= b.n) break;
    const u = k * dt;
    const env = adEnv(u, ATTACK, decay, 0.85);
    // Past the attack, not during it: the envelope is legitimately zero on
    // the first sample, and breaking there renders silence.
    if (u > ATTACK && env < 1e-5) break;
    // The modulator dies well before the carrier: bright strike, pure tail.
    const mEnv = Math.exp(-u / (decay * 0.22));
    const m = Math.sin(TAU * mph) * index * mEnv;
    b.add(i, Math.sin(TAU * ph + m) * env * gain, pan, sendHall, sendPlate);
    ph += freq * dt;
    mph += freq * ratio * dt;
  }
}

/** A terminal line: a filtered noise transient with a pitched blip inside it. */
function tick(b, { t, freq, gain = 0.12, pan = 0 }) {
  const i0 = idx(b, t);
  const len = Math.ceil(0.22 * b.sr);
  const r = rng(Math.round(t * 1000) + 17);
  const svf = new SVF(b.sr);
  const dt = 1 / b.sr;
  let ph = 0;
  for (let k = 0; k < len; k++) {
    const i = i0 + k;
    if (i >= b.n) break;
    const u = k * dt;
    const env = adEnv(u, 0.001, 0.028, 1.4);
    const noise = (r() * 2 - 1) * Math.exp(-u * 220);
    const s = svf.bp(noise, freq * 2.2, 2.4) * 0.8 + Math.sin(TAU * ph) * 0.55;
    b.add(i, s * env * gain, pan, 0.22, 0.5);
    ph += freq * dt;
  }
}

/** rowan's voice: a filtered saw, woodier and lower than avery's sine gate. */
function pluckWood(b, { t, freq, gain = 0.2, decay = 1.6, pan = 0, bend = 0 }) {
  const sawT = sawTable(14);
  const i0 = idx(b, t);
  const len = Math.ceil(decay * 4 * b.sr);
  const svf = new SVF(b.sr);
  const dt = 1 / b.sr;
  let ph = 0;
  for (let k = 0; k < len; k++) {
    const i = i0 + k;
    if (i >= b.n) break;
    const u = k * dt;
    const env = lpgEnv(u, decay);
    if (env < 1e-5 && u > decay) break;
    const f = freq * Math.pow(2, (bend * Math.exp(-u * 3.4)) / 12);
    const y = svf.lp(sawT.read(ph) * 0.55, clamp(f * (1.6 + 5.5 * env), 70, 6000), 2.1);
    b.add(i, y * env * gain, pan, 0.4, 0.34);
    ph += f * dt;
  }
}

/** Sub-and-noise landing for a scene's big move. No drum, just weight. */
function impact(b, { t, gain = 0.4 }) {
  const i0 = idx(b, t);
  const len = Math.ceil(2.4 * b.sr);
  const r = rng(Math.round(t * 613) + 41);
  const lp = new OnePole(b.sr, 260);
  const dt = 1 / b.sr;
  let ph = 0;
  for (let k = 0; k < len; k++) {
    const i = i0 + k;
    if (i >= b.n) break;
    const u = k * dt;
    const env = adEnv(u, 0.006, 0.42, 0.9);
    // Pitch drops an octave over the first fifth of a second.
    const f = hz('D1') * (1 + 1.1 * Math.exp(-u * 14));
    const s = Math.sin(TAU * ph) * 0.9 + lp.lp(r() * 2 - 1) * 0.35 * Math.exp(-u * 9);
    b.add(i, s * env * gain, 0, 0.3, 0.1);
    ph += f * dt;
  }
}

/**
 * Snap a frequency to the nearest pitch the section's pool actually contains,
 * searching an octave either side. A fork's interval is a gesture, not a
 * pitch: a plain transposition drops out-of-mode notes into the harmony —
 * a minor third above D is the very F the consensus spent twenty seconds
 * getting rid of.
 */
function snapToPool(freq, pool) {
  let best = freq;
  let bestErr = Infinity;
  for (const note of pool) {
    const base = hz(note);
    for (const oct of [0.5, 1, 2]) {
      const cand = base * oct;
      const err = Math.abs(Math.log2(cand / freq));
      if (err < bestErr) { bestErr = err; best = cand; }
    }
  }
  return best;
}

/**
 * The set the hyphae draws from and snaps to: the section's chord, reduced to
 * pitch classes and voiced across the pluck octaves (4–5). The free `pool`
 * carries adjacent scale tones (an E and an F, a C and a D) that clash the
 * moment two long-decaying colony notes overlap; restricting the generative
 * layer to chord tones means every simultaneous stack it grows is a chord,
 * never a cluster. It also tightens the harmonic argument rather than fighting
 * it — the negotiate chord names no third, so neither can the colony under it.
 */
const chordVoicing = (chord) => {
  const pcs = [...new Set(chord.map((n) => n.match(/^([A-G]#?)/)[1]))];
  return pcs.flatMap((pc) => [`${pc}4`, `${pc}5`]);
};
const HYPHAE_POOLS = new Map(SECTIONS.map((s) => [s.id, chordVoicing(s.chord)]));

/**
 * The hyphae: the generative layer, and the one that carries the metaphor.
 * A note that fires may fork — a child a fifth or an octave away, a beat or
 * so later, which may fork again — so the texture spreads outward from each
 * strike the way a colony spreads from a spore rather than repeating a
 * pattern. Seeded, so it spreads the same way every render.
 */
function renderHyphae(b) {
  const r = rng(0x4879504841);
  let panWalk = 0;
  const pending = [];

  const fire = (t, freq, gain, depth) => {
    if (t > DURATION - 0.5 || gain < 0.02) return;
    const pool = HYPHAE_POOLS.get(sectionAt(t).id);
    panWalk = clamp(panWalk + (r() - 0.5) * 0.55, -0.9, 0.9);
    const decay = 1.5 + r() * 2.4;
    pluckLPG(b, {
      t, freq, gain, decay,
      pan: panWalk,
      tone: 0.55 + r() * 0.6,
      sendHall: 0.5,
      sendPlate: 0.26,
      wave: TRI, // triangle bed: rounder colony notes, softer when they stack
    });
    if (depth >= 2) return;
    // Fork. A fifth or an octave up is the common case; a fourth down is the
    // branch that runs back toward the root.
    const forks = r() < 0.5 ? 2 : 1;
    for (let k = 0; k < forks; k++) {
      if (r() > 0.52) continue;
      const interval = [7, 12, 5, -5, -12][Math.floor(r() * 5)];
      pending.push({
        t: t + 0.34 + r() * 0.62,
        freq: snapToPool(freq * Math.pow(2, interval / 12), pool),
        gain: gain * (0.46 + r() * 0.2),
        depth: depth + 1,
      });
    }
  };

  for (let t = 3.2; t < DURATION - 1; t += STEP) {
    const sec = sectionAt(t);
    if (r() < sec.density) {
      const pool = HYPHAE_POOLS.get(sec.id);
      const note = pool[Math.floor(r() * pool.length)];
      fire(t + (r() - 0.5) * 0.05, hz(note), (0.085 + r() * 0.07) * sec.gain, 0);
    }
    // Drain forks that have come due, which may themselves fork.
    for (let k = pending.length - 1; k >= 0; k--) {
      if (pending[k].t <= t + STEP) {
        const p = pending.splice(k, 1)[0];
        fire(p.t, p.freq, p.gain, p.depth);
      }
    }
  }
}

/**
 * The negotiation, 65–85s. Two gestures over the same pedal, each landing on
 * its own third: @avery high on F#, @rowan low on F. Their periods differ,
 * so they drift against each other the way two loops of unequal length do —
 * and the periods converge as the rounds do, until at 81.4s they land
 * together on F#.
 */
function renderCounterpoint(b) {
  const CONSENSUS = 81.4;
  const T0 = 65.0;
  const T1 = 85.2;
  const periodA = 3.1;
  // rowan starts slower and is in step with avery by the time they accept.
  const periodB = (t) => lerp(3.62, periodA, clamp((t - T0) / (CONSENSUS - T0), 0, 1));

  for (let t = T0; t < T1; t += periodA) {
    const settle = clamp((t - T0) / 4, 0.35, 1);
    pluckLPG(b, { t, freq: hz('A4'), gain: 0.075 * settle, decay: 2.4, pan: 0.5, tone: 0.7 });
    pluckLPG(b, { t: t + 0.42, freq: hz('F#5'), gain: 0.085 * settle, decay: 3.0, pan: 0.62, tone: 0.55 });
  }

  let t = T0 + 0.9;
  while (t < T1) {
    const settle = clamp((t - T0) / 4, 0.35, 1);
    const third = t < CONSENSUS ? 'F4' : 'F#4';
    pluckWood(b, { t, freq: hz('A3'), gain: 0.08 * settle, decay: 2.2, pan: -0.5 });
    pluckWood(b, { t: t + 0.48, freq: hz(third), gain: 0.09 * settle, decay: 2.8, pan: -0.62 });
    t += periodB(t);
  }
}

/**
 * The resolution itself, held long enough to hear: one sustained tone that
 * enters on F under the last two rounds and glides a semitone to F# across
 * the consensus beat. It is the only portamento in the piece.
 */
function renderResolution(b) {
  const t0 = 78.6;
  const t1 = 88.0;
  const glideStart = 81.35;
  const glideEnd = 82.5;
  const fFlat = hz('F4');
  const fSharp = hz('F#4');
  const i0 = idx(b, t0);
  const i1 = Math.min(b.n, idx(b, t1));
  const svf = new SVF(b.sr);
  const dt = 1 / b.sr;
  let ph = 0;
  let ph2 = 0;
  for (let i = i0; i < i1; i++) {
    const t = i / b.sr;
    const u = clamp((t - glideStart) / (glideEnd - glideStart), 0, 1);
    // Smoothstep, so the semitone arrives rather than being ramped into.
    const f = lerp(fFlat, fSharp, u * u * (3 - 2 * u));
    const env =
      Math.min(1, (t - t0) / 2.6) *
      Math.min(1, (t1 - t) / 3.4) *
      (0.62 + 0.38 * u); // it also gets louder as it resolves
    const vib = 1 + 0.0022 * Math.sin(TAU * 4.3 * t);
    const s = Math.sin(TAU * ph) + 0.3 * Math.sin(TAU * ph2) + 0.1 * Math.sin(TAU * ph * 3);
    const y = svf.lp(s * 0.4, f * (3.2 + 3.0 * u), 0.9);
    b.add(i, y * env * 0.05, -0.08 + 0.16 * u, 0.55, 0.1);
    ph += f * vib * dt;
    ph2 += f * 2 * dt;
  }
}

// ── Cue dispatch ───────────────────────────────────────────────────────
function renderCues(b) {
  for (const cue of CUES) {
    const f = cue.pitch ? hz(cue.pitch) : 0;
    const g = cue.gain ?? 0.2;
    const actorPan = cue.actor === 'avery' ? 0.55 : cue.actor === 'rowan' ? -0.55 : 0;

    switch (cue.kind) {
      case 'tick':
        tick(b, { t: cue.t, freq: f, gain: g, pan: -0.34 + ((cue.t * 7) % 1) * 0.68 });
        break;

      case 'pluck':
        pluckLPG(b, { t: cue.t, freq: f, gain: g, decay: cue.decay ?? 2.0, pan: -0.2 + ((cue.t * 11) % 1) * 0.4 });
        break;

      // An agent joins the room: the gate voice with a bell an octave up
      // riding on it, so a registration reads as an arrival, not a note.
      case 'voice':
        pluckLPG(b, { t: cue.t, freq: f, gain: g, decay: cue.decay ?? 3.0, pan: -0.4 + ((cue.t * 5) % 1) * 0.8, tone: 0.9 });
        pluckFM(b, { t: cue.t + 0.012, freq: f * 2, gain: g * 0.34, decay: 2.6, ratio: 2.005, index: 2.4, pan: 0.3 });
        break;

      // The spore was an FM bell at a 3:1 ratio — bright inharmonic partials
      // that read as a harpsichord tine. A triangle through the gate keeps the
      // long bloom and the "long way down" tail without the sharpness.
      case 'spore':
        pluckLPG(b, { t: cue.t, freq: f, gain: g * 1.5, decay: 4.2, pan: 0, tone: 0.5, sendHall: 1.1, sendPlate: 0.12, wave: TRI });
        break;

      // A line of output that matters: root, fifth, octave, barely staggered.
      case 'bloom':
        [[0, 1, 1], [0.055, 1.5, 0.6], [0.11, 2, 0.4]].forEach(([dt, mult, amp]) =>
          pluckLPG(b, { t: cue.t + dt, freq: f * mult, gain: g * amp, decay: 3.2, pan: -0.5 + dt * 9, tone: 0.8 }));
        break;

      // A scene change: a low tonal accent to mark the cut.
      case 'lift':
        pluckLPG(b, { t: cue.t, freq: hz('D3'), gain: g * 0.32, decay: 2.6, pan: 0, tone: 0.4, sendHall: 0.7 });
        break;

      case 'impact':
        impact(b, { t: cue.t, gain: g });
        break;

      // The camera pushes in: a sub landing under the move, so the frame
      // narrowing is something you feel in the low end.
      case 'zoom':
        impact(b, { t: cue.t + (cue.dur ?? 0.9) * 0.75, gain: g * 0.5 });
        break;

      // A NEGMAS round advances: a low woody knock. Deliberately dry — the
      // rounds are a clock, and a clock with a long tail smears.
      case 'round':
        pluckWood(b, { t: cue.t, freq: hz('D3'), gain: g * 0.5, decay: 0.7, pan: 0 });
        pluckLPG(b, { t: cue.t, freq: hz('D2'), gain: g * 0.42, decay: 0.5, pan: 0, tone: 0.25, sendHall: 0.2, sendPlate: 0.15 });
        tick(b, { t: cue.t + 0.015, freq: hz('A4'), gain: g * 0.3, pan: 0 });
        break;

      // A proposal or a counter, in the proposing agent's own voice and side
      // of the field: @avery is the gate voice on the right, @rowan the saw
      // on the left. You can hear which of them moved without reading a lane.
      case 'move':
        if (cue.actor === 'avery') {
          pluckLPG(b, { t: cue.t, freq: f, gain: g, decay: 2.2, pan: actorPan, tone: 0.75 });
        } else {
          pluckWood(b, { t: cue.t, freq: f, gain: g, decay: 2.0, pan: actorPan });
        }
        break;

      // A rejection: the same gesture bent flat and cut short.
      case 'reject': {
        const f0 = cue.actor === 'avery' ? hz('C5') : hz('Ab3');
        pluckWood(b, { t: cue.t, freq: f0, gain: g * 0.85, decay: 0.78, pan: actorPan, bend: -2.2 });
        pluckWood(b, { t: cue.t + 0.045, freq: f0 * Math.pow(2, -1 / 12), gain: g * 0.5, decay: 0.52, pan: actorPan * 0.6, bend: -1.4 });
        break;
      }

      case 'accept':
        pluckFM(b, { t: cue.t, freq: f, gain: g, decay: 3.0, ratio: 2.01, index: 2.8, pan: actorPan, sendHall: 0.7 });
        break;

      // A task flips to done. Short, bright, and over — satisfaction, not ceremony.
      case 'done':
        pluckFM(b, { t: cue.t, freq: f, gain: g, decay: 1.1, ratio: 4.01, index: 2.2, pan: ((cue.t * 3) % 1) * 0.6 - 0.3, sendHall: 0.4, sendPlate: 0.35 });
        break;

      case 'consensus':
        renderConsensus(b, cue.t, g);
        break;

      default:
        throw new Error(`unknown cue kind: ${cue.kind}`);
    }
  }
}

/**
 * 81.4s, the frame the offer table locks green. Everything that has been
 * held apart arrives at once: a D major chord struck across four octaves,
 * with the sub landing under it.
 */
function renderConsensus(b, t, g) {
  impact(b, { t, gain: g * 0.5 });

  const chord = ['D3', 'A3', 'D4', 'F#4', 'A4', 'D5', 'F#5', 'A5'];
  chord.forEach((note, i) => {
    pluckLPG(b, {
      t: t + i * 0.045,
      freq: hz(note),
      gain: g * (0.27 - i * 0.019),
      decay: 4.2 + i * 0.4,
      pan: (i % 2 ? 1 : -1) * (0.18 + i * 0.07),
      tone: 0.7,
      sendHall: 0.8,
      sendPlate: 0.2,
    });
  });
  // The bell on top, a beat late, so the chord is heard before it is crowned.
  pluckFM(b, { t: t + 0.34, freq: hz('D6'), gain: g * 0.13, decay: 5.0, ratio: 3.01, index: 2.6, sendHall: 0.9, sendPlate: 0.05 });
}

/**
 * The negotiation has to go somewhere across its five rounds, or the round
 * markers read as five identical knocks. A high tone creeps up in level and
 * brightness from the first round to the last and then is simply gone at
 * consensus — the tension leaves rather than resolving, because the
 * resolution is the F# underneath it.
 */
function renderTension(b) {
  const t0 = 66.0;
  const t1 = 81.45;
  const i0 = idx(b, t0);
  const i1 = Math.min(b.n, idx(b, t1 + 0.45));
  const svf = new SVF(b.sr);
  const dt = 1 / b.sr;
  let ph = 0;
  let ph2 = 0;
  const base = hz('E5');
  for (let i = i0; i < i1; i++) {
    const t = i / b.sr;
    const u = clamp((t - t0) / (t1 - t0), 0, 1);
    // Cut off hard at consensus, over about a fifth of a second.
    const release = t > t1 ? Math.max(0, 1 - (t - t1) / 0.45) : 1;
    const env = Math.min(1, (t - t0) / 5) * (0.25 + 0.75 * u * u) * release;
    // A hair sharp, and creeping sharper: the sound of not agreeing.
    const f = base * (1 + 0.004 * u);
    const s = Math.sin(TAU * ph) * 0.7 + Math.sin(TAU * ph2) * 0.3;
    const y = svf.bp(s, f * (1.02 + 0.4 * u), 5.5 + 5 * u);
    b.add(i, y * env * 0.019, 0.12 * Math.sin(TAU * 0.06 * t), 0.6, 0.05);
    ph += f * dt;
    ph2 += f * 1.4983 * dt; // inharmonic partner, so it never settles
  }
}

// ── Render ─────────────────────────────────────────────────────────────
/** Integrated-loudness target. A bed under a screencast, not a music video. */
export const TARGET_LUFS = -17.0;

export function render(sr = 48000, { onProgress = () => {} } = {}) {
  const n = Math.ceil(DURATION * sr);
  const b = makeBuses(sr, n);

  const passes = [
    ['substrate', renderSubstrate],
    ['soil', renderSoil],
    ['pad', renderPad],
    ['throb', renderThrob],
    ['hyphae', renderHyphae],
    ['counterpoint', renderCounterpoint],
    ['tension', renderTension],
    ['resolution', renderResolution],
    ['cues', renderCues],
  ];
  for (const [name, fn] of passes) {
    onProgress(name);
    fn(b);
  }

  onProgress('reverb');
  const hall = new FDNReverb(sr, { rt60: 7.2, damp: 3600, preDelay: 0.032, modDepth: 3.4, modRate: 0.061, seed: 11 });
  const plate = new FDNReverb(sr, { rt60: 1.7, damp: 6200, preDelay: 0.011, modDepth: 1.2, modRate: 0.19, seed: 29 });

  const L = new Float64Array(n);
  const R = new Float64Array(n);
  const dcL = new DCBlock();
  const dcR = new DCBlock();
  // Tilt: nothing below the sub, nothing sharp on top. A 107-second drone is
  // played on a laptop speaker more often than not, and rumble and fizz are
  // what make one tiring there.
  const hpL = new OnePole(sr, 26);
  const hpR = new OnePole(sr, 26);
  const lpL = new OnePole(sr, 11500);
  const lpR = new OnePole(sr, 11500);

  for (let i = 0; i < n; i++) {
    const [hl, hr] = hall.run(b.hall[i]);
    const [pl, pr] = plate.run(b.plate[i]);
    L[i] = softClip(lpL.lp(hpL.hp(dcL.run(b.L[i] + hl * 0.9 + pl * 0.5))));
    R[i] = softClip(lpR.lp(hpR.hp(dcR.run(b.R[i] + hr * 0.9 + pr * 0.5))));
  }

  onProgress('master');
  const comp = glue(L, R, sr);

  // Normalise to the loudness target before limiting, so the limiter is
  // catching the few peaks that remain rather than doing the levelling.
  const preLufs = lufs(L, R, sr);
  const gain = Math.pow(10, (TARGET_LUFS - preLufs) / 20);
  for (let i = 0; i < n; i++) { L[i] *= gain; R[i] *= gain; }
  const lim = limit(L, R, sr, { ceiling: 0.8 });

  // Fades last: the first frame and the last must be silent either way.
  const FADE_IN = 0.35;
  const FADE_OUT = 2.6;
  for (let i = 0; i < n; i++) {
    const t = i / sr;
    const f = Math.min(1, t / FADE_IN) * Math.min(1, Math.max(0, (DURATION - t) / FADE_OUT));
    L[i] *= f;
    R[i] *= f;
  }

  return {
    left: L,
    right: R,
    sampleRate: sr,
    lufs: lufs(L, R, sr),
    lra: lra(L, R, sr),
    truePeakDb: truePeakDb(L, R),
    glueReductionDb: comp.maxGainReductionDb,
    limiterReductionDb: lim.maxGainReductionDb,
  };
}
