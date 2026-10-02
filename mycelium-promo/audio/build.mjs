#!/usr/bin/env node
// Put the sound on a recorded take, or re-mix it.
//
//   node mycelium-promo/audio/build.mjs <video.mp4> [--out <file.mp4>] [--wav <file.wav>]
//
// `record.mjs` already does this after every staged take; run it alone to
// change the sound without re-recording. Reads the video's length and its
// `<video>.sounds.json` (the clicks and keys shotkit noted during the take),
// renders the drone (score.mjs) as the bed, and lets shotkit mix and mux it:
// the picture is copied, not re-encoded, and the video is replaced in place
// unless --out says otherwise.

import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { addSound, probeDuration } from '../../shotkit/src/audio/index.mjs';
import { renderDrone } from './score.mjs';

/**
 * Give a take its sound: the drone under shotkit's clicks and keys, at
 * shotkit's levels (bed at -23 LUFS, the pair at -19, the bed 6 dB under).
 * @param {string} video
 * @param {{out?: string, wav?: string, log?: (m: string) => void}} [opts]
 */
export async function soundTake(video, opts = {}) {
  const log = opts.log ?? (() => {});
  const duration = await probeDuration(video);
  log(`rendering the drone, ${duration.toFixed(1)}s`);
  const bed = renderDrone(duration, 48000, { onProgress: (p) => log(`  · ${p}`) });
  const result = await addSound(video, { bed, out: opts.out, wav: opts.wav, log });
  log(`${result.cues} cues · ${result.lufs.toFixed(1)} LUFS · true peak ${result.truePeakDb.toFixed(1)} dBTP`);
  return result;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const argv = process.argv.slice(2);
  const flag = (name) => {
    const at = argv.indexOf(name);
    return at >= 0 ? argv.splice(at, 2)[1] : undefined;
  };
  const out = flag('--out');
  const wav = flag('--wav');
  const video = argv[0];
  if (!video || video.startsWith('-')) {
    console.error('usage: node mycelium-promo/audio/build.mjs <video.mp4> [--out <file.mp4>] [--wav <file.wav>]');
    process.exit(2);
  }
  const result = await soundTake(resolve(video), {
    out: out && resolve(out),
    wav: wav && resolve(wav),
    log: (m) => console.error(`  ${m}`),
  });
  console.log(result.path);
}
