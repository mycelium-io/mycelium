#!/usr/bin/env node
// Put the sound on a recorded take.
//
//   node mycelium-promo/audio/build.mjs <video.mp4> [--out <with-sound.mp4>] [--wav]
//
// Reads the video's length and its `<video>.sounds.json` (what shotkit writes
// beside a staged take), renders the drone with the clicks and keys on it, and
// muxes it in as AAC. The picture is copied, not re-encoded. Default output is
// the video's own name with `-sound` before the extension.

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';

import { encodeWav } from './dsp.mjs';
import { render } from './score.mjs';

const argv = process.argv.slice(2);
const video = argv.find((a) => !a.startsWith('--') && argv[argv.indexOf(a) - 1] !== '--out');
if (!video) {
  console.error('usage: node audio/build.mjs <video.mp4> [--out <file.mp4>] [--wav]');
  process.exit(2);
}
const outAt = argv.indexOf('--out');
const out = outAt >= 0 ? argv[outAt + 1] : video.replace(/(\.[^.]+)$/, '-sound$1');
const keepWav = argv.includes('--wav');
const say = (m) => process.stdout.write(`  ${m}\n`);

const soundsPath = `${video}.sounds.json`;
const events = existsSync(soundsPath) ? JSON.parse(readFileSync(soundsPath, 'utf8')).events : [];
if (events.length === 0) say(`no ${soundsPath}: the drone alone`);

const duration = Number(
  execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', video]).toString().trim(),
);
say(`rendering ${duration.toFixed(1)}s, ${events.length} clicks and typing runs`);
const mix = render(duration, events, 48000, { onProgress: (p) => say(`  · ${p}`) });
say(`loudness ${mix.lufs.toFixed(1)} LUFS, true peak ${mix.truePeakDb.toFixed(1)} dBTP`);

const wav = out.replace(/\.[^.]+$/, '.wav');
writeFileSync(wav, encodeWav(mix.left, mix.right, mix.sampleRate));
execFileSync('ffmpeg', [
  '-y', '-loglevel', 'error',
  '-i', video, '-i', wav,
  '-map', '0:v:0', '-map', '1:a:0',
  '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
  '-shortest', '-movflags', '+faststart',
  out,
]);
if (!keepWav) rmSync(wav);
say(`wrote ${out}`);
