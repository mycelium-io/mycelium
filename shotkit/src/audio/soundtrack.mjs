// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A take's soundtrack: the clicks and keys from its cues, over an optional bed
 * (a music or ambience file, or any stereo pair a project renders itself),
 * leveled, limited and muxed into the video.
 *
 * The levels work the way a person mixing would set them. The bed is first
 * brought to a reference loudness (`BED_LUFS`), the clicks sit at a fixed size
 * against it, and `target` sets how loud that pair is together. `bedDb` then
 * moves the bed alone, after the overall gain is set, so turning the bed down
 * leaves the clicks exactly where they were. With no bed, the clicks are
 * leveled by their peak instead. The finished track's measured loudness and
 * true peak come back with it, since `bedDb` and the limiter both move it off
 * `target`.
 */

import { writeFileSync } from "node:fs";
import { glue, gainTo, limit, lra, lufs, samplePeakDb, truePeakDb } from "./master.mjs";
import { dbToGain } from "./dsp.mjs";
import { renderFoley } from "./foley.mjs";
import { readCues } from "./cues.mjs";
import { decodeAudio, encodeWav, muxAudio, probeDuration } from "./io.mjs";

/** Where a bed is brought before anything goes on it. */
export const BED_LUFS = -23;

/** With no bed, the loudest click's peak sits this far over `target`. */
export const FOLEY_PEAK_OVER_TARGET = 13;

export const SOUNDTRACK_DEFAULTS = {
  sampleRate: 48000,
  /** The bed and the clicks together, before `bedDb` moves the bed. */
  target: -19,
  /** The bed under the clicks; negative is quieter. */
  bedDb: -6,
  clickDb: 0,
  keyDb: 0,
  fadeIn: 0.35,
  fadeOut: 2.6,
  /** Linear; about -1.9 dBFS, which leaves an AAC encode room for its overshoot. */
  ceiling: 0.8,
};

/**
 * Mix a soundtrack for a video `duration` seconds long.
 *
 * @param {number} duration seconds
 * @param {{t:number, t1?:number, kind:string, chars?:number}[]} cues
 * @param {{bed?: {L: Float64Array, R: Float64Array} | null, foley?: boolean,
 *          target?: number, bedDb?: number, clickDb?: number, keyDb?: number,
 *          fadeIn?: number, fadeOut?: number, ceiling?: number, sampleRate?: number}} [opts]
 */
export function mixSoundtrack(duration, cues, opts = {}) {
  const o = { ...SOUNDTRACK_DEFAULTS, ...opts };
  const sr = o.sampleRate;
  const n = Math.ceil(duration * sr);
  const L = new Float64Array(n);
  const R = new Float64Array(n);

  let bedL = null;
  let bedR = null;
  if (o.bed) {
    bedL = Float64Array.from(o.bed.L.subarray(0, n));
    bedR = Float64Array.from(o.bed.R.subarray(0, n));
    glue(bedL, bedR, sr);
    const g = gainTo(bedL, bedR, sr, BED_LUFS);
    for (let i = 0; i < bedL.length; i++) {
      bedL[i] *= g;
      bedR[i] *= g;
    }
  }

  const foley =
    o.foley === false
      ? null
      : renderFoley(duration, cues, sr, { clickGain: dbToGain(o.clickDb), keyGain: dbToGain(o.keyDb) });

  // The overall gain is set on the pair at the bed's reference level. With no
  // bed there is nothing to measure against, and loudness is the wrong ruler
  // for a few clicks in silence (they meter near -40 LUFS at the size they sit
  // over a bed, and read as almost nothing), so they are leveled by their peak:
  // FOLEY_PEAK_OVER_TARGET dB over the target, -6 dBFS at the default -19.
  let gain = dbToGain(o.target - BED_LUFS);
  if (!bedL && foley) {
    const peak = samplePeakDb(foley.L, foley.R);
    if (Number.isFinite(peak) && peak > -120) gain = dbToGain(o.target + FOLEY_PEAK_OVER_TARGET - peak);
  }
  if (bedL) {
    const refL = new Float64Array(n);
    const refR = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      refL[i] = (bedL[i] ?? 0) + (foley ? foley.L[i] : 0);
      refR[i] = (bedR[i] ?? 0) + (foley ? foley.R[i] : 0);
    }
    gain = gainTo(refL, refR, sr, o.target);
  }
  const trim = dbToGain(o.bedDb);
  for (let i = 0; i < n; i++) {
    const bl = bedL ? (bedL[i] ?? 0) * trim : 0;
    const br = bedR ? (bedR[i] ?? 0) * trim : 0;
    L[i] = (bl + (foley ? foley.L[i] : 0)) * gain;
    R[i] = (br + (foley ? foley.R[i] : 0)) * gain;
  }

  const lim = limit(L, R, sr, { ceiling: o.ceiling });
  const fadeOut = Math.min(o.fadeOut, duration / 4);
  for (let i = 0; i < n; i++) {
    const t = i / sr;
    const f = Math.min(1, t / o.fadeIn) * Math.min(1, Math.max(0, (duration - t) / fadeOut));
    L[i] *= f;
    R[i] *= f;
  }

  return {
    left: L,
    right: R,
    sampleRate: sr,
    lufs: lufs(L, R, sr),
    lra: lra(L, R, sr),
    samplePeakDb: samplePeakDb(L, R),
    truePeakDb: truePeakDb(L, R),
    limiterReductionDb: lim.maxGainReductionDb,
  };
}

/**
 * The mix options out of a spec or parsed flags (`--bed`, `--bed-db`,
 * `--target`, `--click-db`, `--key-db`, `--no-foley`, `--wav`), leaving out
 * what was not given so the defaults apply. Paths must already be absolute.
 * @param {Record<string, any>} spec
 */
export function soundOptions(spec) {
  const pick = ["bed", "bedDb", "target", "clickDb", "keyDb", "foley", "wav"];
  return Object.fromEntries(pick.filter((k) => spec[k] !== undefined).map((k) => [k, spec[k]]));
}

/**
 * Give a video its sound: read its length and cues, mix, and mux. `bed` is a
 * file ffmpeg can read (looped or cut to the video's length) or a stereo pair a
 * caller rendered itself. `out` defaults to the video itself, replaced whole.
 *
 * @param {string} video
 * @param {Parameters<typeof mixSoundtrack>[2] & {bed?: string | {L: Float64Array, R: Float64Array} | null,
 *          out?: string, wav?: string, log?: (m: string) => void}} [opts]
 */
export async function addSound(video, opts = {}) {
  const log = opts.log ?? (() => {});
  const sr = opts.sampleRate ?? SOUNDTRACK_DEFAULTS.sampleRate;
  const duration = await probeDuration(video);
  const cues = readCues(video);
  const bed = typeof opts.bed === "string" ? await decodeAudio(opts.bed, duration, sr) : (opts.bed ?? null);
  log(`mixing ${duration.toFixed(1)}s: ${cues.length} cues${bed ? ", over a bed" : ""}`);
  const track = mixSoundtrack(duration, cues, { ...opts, bed });
  if (opts.wav) writeFileSync(opts.wav, encodeWav(track.left, track.right, sr));
  const out = await muxAudio(video, track, opts.out ?? video);
  const { left: _l, right: _r, ...meters } = track;
  return { path: out, duration, cues: cues.length, bed: Boolean(bed), ...meters };
}
