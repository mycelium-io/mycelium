#!/usr/bin/env node
// Renders the backing track to assets/mycelium-score.mp3.
//
//   npm run audio            # render + encode
//   npm run audio -- --wav   # also keep the intermediate 48kHz WAV
//
// FFmpeg comes from the system if it is on PATH, otherwise from the
// ffmpeg-static devDependency. The WAV is an intermediate; the MP3 is the
// asset index.html loads.

import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { encodeWav } from './dsp.mjs';
import { DURATION, render } from './score.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const assets = join(root, 'assets');
const wavPath = join(assets, 'mycelium-score.wav');
const mp3Path = join(assets, 'mycelium-score.mp3');

function ffmpeg() {
  try {
    execFileSync('ffmpeg', ['-version'], { stdio: 'ignore' });
    return 'ffmpeg';
  } catch {
    try {
      return createRequire(import.meta.url)('ffmpeg-static');
    } catch {
      throw new Error(
        'No ffmpeg. Install one (apt install ffmpeg / brew install ffmpeg) ' +
          'or run `npm install` to pull the ffmpeg-static devDependency.',
      );
    }
  }
}

const keepWav = process.argv.includes('--wav');
const started = process.hrtime.bigint();
const say = (msg) => process.stdout.write(`  ${msg}\n`);

mkdirSync(assets, { recursive: true });

say(`rendering ${DURATION}s at 48kHz`);
const mix = render(48000, { onProgress: (pass) => say(`  · ${pass}`) });

writeFileSync(wavPath, encodeWav(mix.left, mix.right, mix.sampleRate));

const bin = ffmpeg();
execFileSync(
  bin,
  [
    '-y', '-loglevel', 'error',
    '-i', wavPath,
    '-codec:a', 'libmp3lame',
    '-b:a', '160k',
    '-ar', '48000',
    '-ac', '2',
    mp3Path,
  ],
  { stdio: 'inherit' },
);

if (!keepWav) rmSync(wavPath, { force: true });

const kb = (p) => `${(statSync(p).size / 1024).toFixed(0)} KB`;
const secs = Number(process.hrtime.bigint() - started) / 1e9;
say(`${mix.lufs.toFixed(1)} LUFS · LRA ${mix.lra.toFixed(1)} LU · true peak ${mix.truePeakDb.toFixed(1)} dBFS`);
say(`glue -${mix.glueReductionDb.toFixed(1)} dB · limiter -${mix.limiterReductionDb.toFixed(1)} dB`);
say(`wrote assets/mycelium-score.mp3 (${kb(mp3Path)}) in ${secs.toFixed(1)}s`);
if (keepWav) say(`kept assets/mycelium-score.wav (${kb(wavPath)})`);
