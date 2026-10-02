// The demo's drone: the bed under the take, which is mycelium's own music.
// Everything else about the sound (the clicks and keys of the person driving
// the take, placing them where they show, leveling, limiting, the mux) is
// shotkit's (`shotkit/src/audio`); this hands it a stereo pair as the bed.
//
// The drone is the old promo score's bed alone: sine partials on a D chord
// that breathe on their own slow LFOs, pink-noise "soil" through a slowly
// moving bandpass, a dark pad, and a sub swell every couple of beats, through
// a long hall. Nothing in it is plucked or bright; it sits under the video
// rather than scoring it. It is returned unleveled: shotkit brings a bed to
// its reference loudness before anything goes on it.

import {
  FDNReverb, OnePole, PinkNoise, SVF, DCBlock, TAU,
  clamp, hz, makeBus, rng, hollowTable, softClip, swellEnv,
} from '../../shotkit/src/audio/dsp.mjs';

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
            b.add(i, s * 0.055, v.pan * Math.cos(TAU * (v.panRate * t + v.lfoPhase)), 0.5);
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
    b.add(i, s * env, Math.sin(TAU * 0.008 * t) * 0.5, 0.34);
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
        b.add(i, y * amp * fade * sec.gain, pan * Math.cos(TAU * panRate * t), 0.62);
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
      b.add(i, s * swellEnv(u, dur, 0.3) * 0.045 * sec.gain, 0, 0.12);
    }
  }
}

/**
 * The drone for a video `duration` seconds long, as the stereo pair shotkit
 * takes for a bed: `addSound(video, { bed: renderDrone(duration) })`.
 * @returns {{L: Float64Array, R: Float64Array}}
 */
export function renderDrone(duration, sr = 48000, { onProgress = () => {} } = {}) {
  const n = Math.ceil(duration * sr);
  const secs = sections(duration);
  const b = makeBus(sr, n);
  for (const [name, fn] of [['substrate', renderSubstrate], ['soil', renderSoil], ['pad', renderPad], ['throb', renderThrob]]) {
    onProgress(name);
    fn(b, secs, duration);
  }

  onProgress('hall');
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
    const [hl, hr] = hall.run(b.sendA[i]);
    L[i] = softClip(lpL.lp(hpL.hp(dcL.run(b.L[i] + hl * 0.9))));
    R[i] = softClip(lpR.lp(hpR.hp(dcR.run(b.R[i] + hr * 0.9))));
  }
  return { L, R };
}
