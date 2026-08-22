// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Getting frames out of a page and into an encoder, at a steady rate.
 *
 * Two halves, because they fail in different ways and only one of them needs a
 * browser. `frameSource` is the browser half: it holds the newest frame the page
 * has produced, however that page is being watched. `startPump` is the clock: it
 * writes whatever the source is holding, every 1/fps, whether the page changed
 * or not — a still page costs repeats of one JPEG, and the video's timeline
 * stays wall-clock true.
 *
 * The clock knows nothing about Playwright, which is the point: the lifecycle
 * bugs live here (a beat that throws, an encoder that died three seconds ago, a
 * take that overruns its cap), and they are reachable in a test with a source
 * that is an object holding a buffer.
 */

import { jpegSize } from "./encode.mjs";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** How long a giving-up take waits for ffmpeg before killing it. */
const ABORT_FLUSH_MS = 5_000;

/**
 * @typedef {object} FrameSource
 * @property {string} mode how frames are being taken: `screencast` or `shots`
 * @property {Buffer|null} latest the newest frame, or null before the first
 * @property {() => Promise<void>} stop
 */

/**
 * Watch a page.
 *
 * A CDP screencast is the browser pushing what it composites — real frames at
 * real times, the app's own transitions included. The screenshot loop is the
 * fallback: slower, coarser, and dependent on nothing but `page.screenshot`.
 *
 * @param {import("playwright").Page} page
 * @param {import("playwright").BrowserContext} context
 * @param {{capture?:string, quality:number, frame:{width:number,height:number,scale:number},
 *          log?:(m:string)=>void}} opts
 * @returns {Promise<FrameSource>}
 */
export async function frameSource(page, context, opts) {
  if ((opts.capture ?? "screencast") !== "shots") {
    const cast = await screencast(page, context, opts);
    if (cast) return cast;
    opts.log?.("no screencast frames; falling back to a screenshot loop");
  }
  return shots(page, opts);
}

async function screencast(page, context, opts) {
  const cdp = await context.newCDPSession(page).catch(() => null);
  if (!cdp) return null;

  const source = { mode: "screencast", latest: null, stop: () => cdp.send("Page.stopScreencast").catch(() => {}) };
  cdp.on("Page.screencastFrame", (f) => {
    source.latest = Buffer.from(f.data, "base64");
    // Unacknowledged frames stop the stream after a few, so this is not
    // bookkeeping: it is what keeps the frames coming.
    cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
  });
  await cdp.send("Page.startScreencast", {
    format: "jpeg",
    quality: opts.quality,
    maxWidth: Math.round(opts.frame.width * opts.frame.scale),
    maxHeight: Math.round(opts.frame.height * opts.frame.scale),
    everyNthFrame: 1,
  });

  for (let i = 0; i < 40 && !source.latest; i++) await sleep(50);
  if (source.latest) return source;
  await source.stop();
  return null;
}

function shots(page, opts) {
  let running = true;
  const source = { mode: "shots", latest: null, stop: async () => {} };
  const loop = (async () => {
    while (running) {
      try {
        source.latest = await page.screenshot({
          type: "jpeg",
          quality: opts.quality,
          animations: "allow",
          caret: "hide",
        });
      } catch {
        if (running) await sleep(100);
      }
    }
  })();
  source.stop = async () => {
    running = false;
    await loop.catch(() => {});
  };
  return waitForFirst(source);
}

async function waitForFirst(source) {
  for (let i = 0; i < 60 && !source.latest; i++) await sleep(50);
  return source;
}

/**
 * Write the source's newest frame on every beat until stopped.
 *
 * @param {{source: FrameSource, fps: number, maxFrames: number,
 *          encoder: (size:{width:number,height:number}) => any,
 *          log?: (m:string) => void}} opts
 */
export function startPump(opts) {
  const period = 1000 / opts.fps;
  const log = opts.log ?? (() => {});
  let encoder = null;
  let size = { width: 0, height: 0 };
  let stopped = false;
  let truncated = false;
  let timer = null;
  let failure = null;
  let warnedSaturated = false;

  /** Resolves the moment the take is no longer worth continuing. */
  let onTrouble = () => {};
  const trouble = new Promise((resolve) => {
    onTrouble = resolve;
  });

  // Nothing in here may throw: it runs on a timer, where a throw is an uncaught
  // exception in whatever process hosts the daemon rather than a failed shot.
  // Anything that goes wrong is held, and raised when the take ends.
  const beat = (n, startedAt) => {
    if (stopped) return;
    try {
      const frame = opts.source.latest;
      if (frame) {
        if (!encoder) {
          size = jpegSize(frame);
          if (!size.width) throw new Error("the first frame was not a readable JPEG");
          encoder = opts.encoder(size);
          log(`encoding ${size.width}x${size.height} @ ${opts.fps}fps`);
        }
        if (encoder.frames >= opts.maxFrames) truncated = true;
        else encoder.write(frame);
        if (encoder.saturated && !warnedSaturated) {
          warnedSaturated = true;
          log("the encoder is behind; frames are buffering in node until it catches up");
        }
        // An encoder that died takes the rest of the take with it — there is
        // nothing left to record into, and the flow would otherwise run to the
        // end before anyone found out.
        if (encoder.failure) failure ??= encoder.failure;
      }
    } catch (err) {
      failure ??= err;
    }
    if (failure) onTrouble("encoder");
    const next = startedAt + (n + 1) * period - Date.now();
    timer = setTimeout(() => beat(n + 1, startedAt), Math.max(0, next));
  };

  beat(0, Date.now());

  const halt = async () => {
    if (stopped) return;
    stopped = true;
    if (timer) clearTimeout(timer);
    await opts.source.stop();
  };

  return {
    mode: opts.source.mode,
    trouble,
    get truncated() {
      return truncated;
    },
    get failure() {
      return failure;
    },
    /** How long the take may run before the frame cap bites. */
    budgetMs: (opts.maxFrames / opts.fps) * 1000,

    async stop() {
      await halt();
      if (failure) throw failure;
      if (!encoder) throw new Error("nothing was captured — the page never produced a frame");
      const { frames } = await encoder.finish();
      return { frames, ...size };
    },

    /**
     * Give up, but close the file properly: a take that failed on its third
     * action is still the most useful thing to look at, and a half-written
     * container is not playable. The wait is short, because by here something
     * has already gone wrong and the file is a consolation, not the deliverable.
     */
    async abort() {
      await halt();
      await encoder?.finish(ABORT_FLUSH_MS).catch(() => {});
    },
  };
}
