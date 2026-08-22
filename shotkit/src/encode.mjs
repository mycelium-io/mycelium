// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Frames in, one video file out.
 *
 * Frames go down ffmpeg's stdin as they are captured rather than being kept for
 * the end, so a minute of 1280x800 normally costs a pipe rather than a gigabyte
 * and the encode finishes about when the recording does. "Normally" is the
 * honest word: when ffmpeg falls behind, node buffers, and `write` reports that
 * so the pump can say so. Dropping the frame instead would be worse — the file
 * would come out shorter than the take, with no sign of where the time went.
 *
 * Which ffmpeg is a real question on this machine and not a detail. Playwright
 * ships one for its own video recording, and it is always there once browsers
 * are installed — but it is built `--disable-everything` with VP8 and WebM
 * enabled and nothing else. So H.264 and GIF depend on a full ffmpeg being on
 * PATH, and the format list is probed rather than assumed: better to say "this
 * ffmpeg can only write webm" up front than to hand back a broken mp4.
 */

import { spawn } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { platform } from "node:os";
import { join } from "node:path";
import { BROWSERS_DIR } from "./browser.mjs";

/** Playwright's own build, wherever its browsers live. */
function bundledFfmpeg() {
  const inner = { linux: "ffmpeg-linux", darwin: "ffmpeg-mac", win32: "ffmpeg-win64.exe" }[platform()];
  if (!inner || !existsSync(BROWSERS_DIR)) return null;
  const dirs = readdirSync(BROWSERS_DIR)
    .filter((d) => d.startsWith("ffmpeg-"))
    .sort((a, b) => Number(b.split("-").pop()) - Number(a.split("-").pop()));
  for (const d of dirs) {
    const p = join(BROWSERS_DIR, d, inner);
    if (existsSync(p)) return p;
  }
  return null;
}

const run = (cmd, args) =>
  new Promise((resolve) => {
    const child = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    child.stdout.on("data", (c) => (out += c));
    child.stderr.on("data", (c) => (out += c));
    child.on("error", () => resolve(null));
    child.on("close", (code) => resolve(code === 0 ? out : null));
  });

/** @type {{path:string, source:string, encoders:string[], formats:string[]}|null} */
let cached = null;

/**
 * The ffmpeg this machine will use, and what it can actually write.
 * Probed once and held — the daemon asks on every recording.
 * @param {{force?: boolean}} [opts]
 */
export async function findEncoder(opts = {}) {
  if (cached && !opts.force) return cached;
  const candidates = [process.env.SHOTKIT_FFMPEG, "ffmpeg", bundledFfmpeg()].filter(Boolean);
  for (const path of candidates) {
    const listing = await run(path, ["-hide_banner", "-encoders"]);
    if (!listing) {
      // Falling through is right for a guess and wrong for an instruction: an
      // ffmpeg someone named by hand and got silently replaced is a mystery
      // about the resulting file, not a recoverable condition.
      if (path === process.env.SHOTKIT_FFMPEG) {
        throw new Error(`SHOTKIT_FFMPEG=${path} could not list its encoders; it is not a usable ffmpeg.`);
      }
      continue;
    }
    const encoders = ["libx264", "libx265", "libvpx", "libvpx-vp9", "gif"].filter((e) =>
      new RegExp(`^\\s*\\S+\\s+${e}\\s`, "m").test(listing),
    );
    const formats = [];
    if (encoders.includes("libx264")) formats.push("mp4");
    if (encoders.includes("libvpx") || encoders.includes("libvpx-vp9")) formats.push("webm");
    if (encoders.includes("gif")) formats.push("gif");
    const source = path === process.env.SHOTKIT_FFMPEG ? "SHOTKIT_FFMPEG" : path === "ffmpeg" ? "PATH" : "playwright";
    cached = { path, source, encoders, formats };
    return cached;
  }
  throw new Error(
    "no ffmpeg. Install one (brew install ffmpeg / apt install ffmpeg), point SHOTKIT_FFMPEG at a binary, " +
      "or run `npx playwright install` — Playwright ships a webm-only build shotkit can borrow.",
  );
}

/** Reset the probe; for tests and for `shot doctor` after an install. */
export function forgetEncoder() {
  cached = null;
}

/** The best container this ffmpeg can write, most useful first. */
export function defaultFormat(caps) {
  return caps.formats[0] ?? "webm";
}

/**
 * ffmpeg's argument list for one take.
 *
 * `scale` is pinned to the first frame's size rounded to even numbers: the
 * screencast can hand back an odd or off-by-one frame when a page resizes
 * itself, and both H.264 and VP8 refuse odd dimensions in 4:2:0.
 *
 * @param {{format:string, fps:number, width:number, height:number,
 *          crf?:number, out:string}} opts
 */
export function encodeArgs({ format, fps, width, height, crf, out }) {
  const w = width - (width % 2);
  const h = height - (height % 2);
  // `pipe:0` rather than `-`: Playwright's stripped build registers the pipe
  // protocol but not the bare-dash spelling of it, and both work everywhere.
  const input = ["-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe",
    "-vcodec", "mjpeg", "-framerate", String(fps), "-i", "pipe:0"];
  if (format === "mp4") {
    return [...input, "-vf", `scale=${w}:${h}`, "-c:v", "libx264", "-preset", "veryfast",
      "-crf", String(crf ?? 20), "-pix_fmt", "yuv420p", "-movflags", "+faststart", out];
  }
  if (format === "webm") {
    return [...input, "-vf", `scale=${w}:${h}`, "-c:v", "libvpx", "-b:v", "0",
      "-crf", String(crf ?? 30), "-deadline", "good", "-cpu-used", "3", "-pix_fmt", "yuv420p", out];
  }
  if (format === "gif") {
    const rate = Math.min(fps, 18);
    return [...input, "-vf",
      `fps=${rate},scale=${w}:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4`,
      "-loop", "0", out];
  }
  throw new Error(`unknown video format "${format}"`);
}

/** How long a closed pipe may take to become a finished file. */
const FLUSH_TIMEOUT_MS = 60_000;

/**
 * Start an encoder. Write JPEG frames to `write()`, then `await finish()`.
 *
 * @param {{format:string, fps:number, width:number, height:number, crf?:number,
 *          out:string, ffmpeg:string}} opts
 */
export function startEncoder(opts) {
  const args = encodeArgs(opts);
  const child = spawn(opts.ffmpeg, args, { stdio: ["pipe", "ignore", "pipe"] });
  let stderr = "";
  let failed = null;
  let frames = 0;
  let saturated = false;
  child.stderr.on("data", (c) => (stderr += c));
  child.on("error", (err) => (failed ??= err));
  // A dead encoder must not take the recorder down with an EPIPE mid-take; the
  // failure is reported when the take ends, with ffmpeg's own diagnostics.
  child.stdin.on("error", (err) => (failed ??= err));
  child.stdin.on("drain", () => (saturated = false));

  /**
   * The exit, captured now rather than when someone asks for it.
   *
   * A ChildProcess emits `close` once and never replays it. An ffmpeg that died
   * on its own arguments dies within milliseconds of spawning — long before the
   * take ends — so a listener registered at `finish()` would be waiting for an
   * event that already happened, and the take would hang instead of reporting
   * what ffmpeg said.
   */
  const exited = new Promise((resolve) => {
    child.on("close", (code) => {
      if (code !== 0 && !failed) failed = new Error(`ffmpeg exited ${code}\n${stderr.trim()}`);
      resolve();
    });
    // A spawn that never started emits `error`, and on some platforms no
    // `close` after it; resolving here keeps that from hanging too.
    child.on("error", () => setImmediate(resolve));
  });

  /** @type {Promise<{frames:number}>|null} */
  let ending = null;
  return {
    args,
    get frames() {
      return frames;
    },
    /** Whether frames are buffering in node right now, waiting on ffmpeg. */
    get saturated() {
      return saturated;
    },
    /** The failure, if this encoder is already gone. */
    get failure() {
      return failed;
    },
    write(buf) {
      if (failed || child.stdin.destroyed) return false;
      frames += 1;
      // The return value is real backpressure: false means this frame is
      // sitting in node's buffer rather than in ffmpeg. The pump reports it
      // rather than dropping the frame, which would silently shorten the take.
      const drained = child.stdin.write(buf);
      if (!drained) saturated = true;
      return drained;
    },
    /**
     * Close the pipe and wait for the file. Safe to call twice; the second
     * caller gets the first one's outcome, including its bound.
     * @param {number} [timeoutMs] how long to wait before killing ffmpeg
     */
    finish(timeoutMs = FLUSH_TIMEOUT_MS) {
      ending ??= (async () => {
        if (!child.stdin.destroyed) child.stdin.end();
        // ffmpeg flushes and exits in well under a second once the pipe closes;
        // a bound on that wait is what keeps a wedged encoder from wedging the
        // daemon behind it.
        const killer = setTimeout(() => {
          failed ??= new Error(`ffmpeg did not finish within ${timeoutMs}ms; killed`);
          child.kill("SIGKILL");
        }, timeoutMs);
        try {
          await exited;
        } finally {
          clearTimeout(killer);
        }
        if (failed) throw failed;
        if (!frames) throw new Error("no frames were captured");
        return { frames };
      })();
      return ending;
    },
    kill() {
      child.kill("SIGKILL");
    },
  };
}

/** Width/height out of a JPEG's SOF marker, without decoding it. */
export function jpegSize(buf) {
  let i = 2;
  while (i < buf.length - 9) {
    if (buf[i] !== 0xff) {
      i += 1;
      continue;
    }
    const marker = buf[i + 1];
    // SOF0-SOF15, minus the four markers in that range that are not frame headers.
    if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
      return { height: buf.readUInt16BE(i + 5), width: buf.readUInt16BE(i + 7) };
    }
    i += 2 + buf.readUInt16BE(i + 2);
  }
  return { width: 0, height: 0 };
}
