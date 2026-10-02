// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Getting audio in and out: a WAV writer, and ffmpeg for everything that has
 * to read a file or write a container (a bed's mp3, the length of a video, the
 * finished mux). Samples go to ffmpeg as raw float32 on a pipe, so a soundtrack
 * never round-trips through a 16-bit file on its way into the video.
 */

import { spawn } from "node:child_process";
import { renameSync, rmSync } from "node:fs";
import { extname } from "node:path";
import { AUDIO_CODECS, findEncoder } from "../encode.mjs";
import { clamp } from "./dsp.mjs";

/** A stereo 16-bit PCM WAV, for keeping or auditioning a track on its own. */
export function encodeWav(left, right, sr) {
  const frames = left.length;
  const bytes = frames * 4;
  const buf = Buffer.alloc(44 + bytes);
  buf.write("RIFF", 0);
  buf.writeUInt32LE(36 + bytes, 4);
  buf.write("WAVE", 8);
  buf.write("fmt ", 12);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(2, 22);
  buf.writeUInt32LE(sr, 24);
  buf.writeUInt32LE(sr * 4, 28);
  buf.writeUInt16LE(4, 32);
  buf.writeUInt16LE(16, 34);
  buf.write("data", 36);
  buf.writeUInt32LE(bytes, 40);
  for (let i = 0; i < frames; i++) {
    buf.writeInt16LE(Math.round(clamp(left[i], -1, 1) * 32767), 44 + i * 4);
    buf.writeInt16LE(Math.round(clamp(right[i], -1, 1) * 32767), 46 + i * 4);
  }
  return buf;
}

/** Interleave a stereo pair as little-endian float32, the shape ffmpeg's f32le reads. */
export function interleave(L, R) {
  const buf = Buffer.alloc(L.length * 8);
  for (let i = 0; i < L.length; i++) {
    buf.writeFloatLE(L[i], i * 8);
    buf.writeFloatLE(R[i], i * 8 + 4);
  }
  return buf;
}

/** Run ffmpeg, feeding it `input` on stdin; resolves with stdout, rejects with its stderr. */
function ffmpeg(path, args, input) {
  return new Promise((resolve, reject) => {
    const child = spawn(path, ["-hide_banner", "-loglevel", "error", ...args], { stdio: ["pipe", "pipe", "pipe"] });
    const out = [];
    let err = "";
    child.stdout.on("data", (c) => out.push(c));
    child.stderr.on("data", (c) => (err += c));
    child.on("error", reject);
    child.on("close", (code) =>
      code === 0 ? resolve(Buffer.concat(out)) : reject(new Error(`ffmpeg exited ${code}\n${err.trim()}`)),
    );
    child.stdin.on("error", () => {});
    if (input) child.stdin.end(input);
    else child.stdin.end();
  });
}

/**
 * An ffmpeg that can do sound, or a clear error. Playwright's bundled build
 * writes webm video and nothing else, so sound needs a full ffmpeg.
 * @param {string} [format] the container the sound is going into
 */
export async function soundFfmpeg(format) {
  if (format && !AUDIO_CODECS[format]) {
    throw new Error(`a ${format} has no sound track; record mp4 or webm to give a take its sound.`);
  }
  const caps = await findEncoder();
  if (format && !caps.audio.includes(format)) {
    throw new Error(
      `this ffmpeg (${caps.source === "playwright" ? "Playwright's webm-only build" : caps.path}) has no ` +
        `${AUDIO_CODECS[format] ?? "audio"} encoder, so it cannot put sound in ${format}. ` +
        "Install a full ffmpeg (brew install ffmpeg / apt install ffmpeg), or point SHOTKIT_FFMPEG at one.",
    );
  }
  return caps.path;
}

/** A media file's length in seconds, read from what ffmpeg says about it. */
export async function probeDuration(file) {
  const path = (await findEncoder()).path;
  // `-i` alone exits non-zero ("no output file"), but prints the header first.
  const text = await new Promise((resolve) => {
    const child = spawn(path, ["-hide_banner", "-i", file], { stdio: ["ignore", "ignore", "pipe"] });
    let err = "";
    child.stderr.on("data", (c) => (err += c));
    child.on("error", () => resolve(""));
    child.on("close", () => resolve(err));
  });
  const m = /Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)/.exec(text);
  if (!m) throw new Error(`could not read the length of ${file}`);
  return Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]);
}

/**
 * Decode any audio file ffmpeg can read to a stereo pair at `sr`, exactly
 * `duration` seconds long: looped when it is shorter, cut when it is longer.
 * @returns {Promise<{L: Float64Array, R: Float64Array}>}
 */
export async function decodeAudio(file, duration, sr = 48000) {
  const path = await soundFfmpeg();
  const raw = await ffmpeg(path, [
    "-stream_loop", "-1", "-i", file, "-t", String(duration),
    "-f", "f32le", "-ac", "2", "-ar", String(sr), "pipe:1",
  ]);
  const n = Math.ceil(duration * sr);
  const L = new Float64Array(n);
  const R = new Float64Array(n);
  const frames = Math.min(n, Math.floor(raw.length / 8));
  for (let i = 0; i < frames; i++) {
    L[i] = raw.readFloatLE(i * 8);
    R[i] = raw.readFloatLE(i * 8 + 4);
  }
  return { L, R };
}

/**
 * Put a soundtrack into a video, replacing any sound it had. The picture is
 * copied, not re-encoded. Writing to `out` equal to `video` is safe: the mux
 * goes to a temporary file that replaces the original only once it is whole.
 */
export async function muxAudio(video, track, out = video) {
  const format = extname(out).slice(1).toLowerCase();
  const path = await soundFfmpeg(format);
  const codec = AUDIO_CODECS[format];
  const tmp = `${out}.mux-${process.pid}${extname(out)}`;
  try {
    await ffmpeg(
      path,
      [
        "-y",
        "-i", video,
        "-f", "f32le", "-ar", String(track.sampleRate), "-ac", "2", "-i", "pipe:0",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", codec, "-b:a", format === "mp4" ? "160k" : "128k",
        "-shortest",
        ...(format === "mp4" ? ["-movflags", "+faststart"] : []),
        tmp,
      ],
      interleave(track.left, track.right),
    );
    renameSync(tmp, out);
  } catch (err) {
    rmSync(tmp, { force: true });
    throw err;
  }
  return out;
}
