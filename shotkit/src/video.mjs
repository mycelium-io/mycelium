// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Short videos: the same page, the same actions, but recorded.
 *
 * A screenshot answers "what does it look like"; a take answers "what happens
 * when you use it". The difference is entirely in the parts a still does not
 * need — a pointer that travels to the thing it is about to press, a click you
 * can see land, and a camera that pushes in so the detail being demonstrated is
 * legible at the size a README embeds.
 *
 * Three pieces, kept apart on purpose:
 *
 *   cursor.mjs   what the page draws (pointer, ripple, camera transform)
 *   this file    the take: a frame pump, and a cinematic reading of the actions
 *   encode.mjs   frames to a file
 *
 * The action vocabulary is the one `--do` already speaks. A recording does not
 * get its own script format: `click:Negotiate` is a click in a screenshot and a
 * glide-press-settle in a take, because the difference between those is the
 * recorder's business and not the caller's.
 *
 * Frames come from a CDP screencast — the browser pushing what it composites,
 * which is a real recording of real timing, including the app's own transitions.
 * A screenshot loop is the fallback where that is unavailable; it produces the
 * same file, more slowly and with the page's animation sampled coarsely.
 */

import { OVERLAY_DEFAULTS, installOverlay } from "./cursor.mjs";
import { defaultFormat, findEncoder, jpegSize, startEncoder } from "./encode.mjs";
import { frameOf, policyOf, preparePage, seedStorage } from "./engine.mjs";
import { runActions } from "./actions.mjs";
import { palette } from "./theme.mjs";

/** Timing, in ms. Beats a viewer can follow rather than the fastest that works. */
export const TIMING = {
  moveMs: 620,
  dwellMs: 620,
  zoomMs: 620,
  leadInMs: 500,
  tailMs: 1000,
  typeDelayMs: 55,
  settleMs: 130,
};

export const VIDEO_DEFAULTS = {
  fps: 30,
  scale: 1,
  width: 1280,
  height: 800,
  quality: 92,
  zoom: 1.6,
  maxSeconds: 90,
};

/**
 * The container this take will land in, and the ffmpeg that can write it.
 *
 * Resolved before the file name is chosen, because the default is whatever the
 * machine can actually do — an mp4 where a full ffmpeg is installed, webm off
 * Playwright's bundled build — and the extension has to agree with it.
 * @param {Record<string, any>} spec
 */
export async function resolveFormat(spec) {
  const caps = await findEncoder();
  const format = spec.format ?? defaultFormat(caps);
  if (!caps.formats.includes(format)) {
    throw new Error(
      `this ffmpeg cannot write ${format} (it offers ${caps.formats.join(", ") || "nothing"}). ` +
        `It is ${caps.source === "playwright" ? "Playwright's bundled build, which is webm-only" : caps.path}. ` +
        `Install a full ffmpeg, or pass --format ${caps.formats[0] ?? "webm"}.`,
    );
  }
  return { caps, format };
}

/**
 * Read a `zoom:` argument: `out` | `2` | `<sel>` | `<sel>@2.2`.
 *
 * A bare number is a factor on the pointer, anything else is a target — and a
 * selector can hold digits and colons, so the factor is only ever the tail
 * after the last `@`.
 *
 * @param {string} arg @param {number} fallback the configured `--zoom`
 * @returns {{target: string, z: number}}
 */
export function parseZoom(arg, fallback) {
  const text = String(arg ?? "").trim();
  if (!text || text === "out" || text === "1") return { target: "", z: 1 };
  const cut = text.lastIndexOf("@");
  const tail = cut > 0 ? Number(text.slice(cut + 1)) : Number(text);
  const numeric = Number.isFinite(tail) && tail > 0;
  return {
    target: cut > 0 ? text.slice(0, cut) : numeric ? "" : text,
    z: numeric ? tail : fallback,
  };
}

const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
/** Ease in and out — a pointer that starts and stops, rather than teleports. */
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

/**
 * Record one take.
 *
 * @param {import("./engine.mjs").Engine} eng
 * @param {Record<string, any>} spec
 * @param {{log?: (m:string) => void, out: string}} ctx `out` is the file to write
 */
export async function record(eng, spec, ctx) {
  const log = ctx.log ?? (() => {});
  const { caps, format } = await resolveFormat(spec);

  const fps = clamp(Math.round(spec.fps ?? VIDEO_DEFAULTS.fps), 5, 60);
  const timing = {
    ...TIMING,
    ...(spec.moveMs !== undefined ? { moveMs: spec.moveMs } : {}),
    ...(spec.dwell !== undefined ? { dwellMs: spec.dwell } : {}),
    ...(spec.zoomMs !== undefined ? { zoomMs: spec.zoomMs } : {}),
    ...(spec.leadIn !== undefined ? { leadInMs: spec.leadIn } : {}),
    ...(spec.tail !== undefined ? { tailMs: spec.tail } : {}),
  };

  // Motion is the point here, so two still-capture defaults invert: the app's
  // own transitions have to run, and one device pixel per video pixel keeps the
  // file a size a README can hold.
  const frame = frameOf({
    ...spec,
    width: spec.width ?? VIDEO_DEFAULTS.width,
    height: spec.height ?? VIDEO_DEFAULTS.height,
    scale: spec.scale ?? VIDEO_DEFAULTS.scale,
    reducedMotion: false,
  });

  const browser = await eng.start(policyOf(spec));
  const context = await browser.newContext(eng.contextOptions(frame));
  const start = { x: Math.round(frame.width * 0.14), y: Math.round(frame.height * 0.2) };
  await context.addInitScript(installOverlay, {
    ...OVERLAY_DEFAULTS,
    cursor: spec.cursor !== false,
    accent: spec.accent ?? palette(frame.theme).accent,
    startX: start.x,
    startY: start.y,
    ...(spec.cursorSize ? { size: spec.cursorSize } : {}),
  });
  if (spec.storage) await seedStorage(context, spec.storage);

  const t0 = Date.now();
  const page = await context.newPage();
  let pump = null;
  try {
    await page.goto(spec.url, { waitUntil: spec.waitUntil ?? "domcontentloaded", timeout: spec.timeout ?? 30_000 });
    // Waits, hidden selectors and extra CSS, but not the actions: those are the
    // take, and they have to happen with the camera rolling.
    await preparePage(page, { ...spec, do: [] });
    await page.mouse.move(start.x, start.y);
    await page.evaluate(([x, y]) => window.__shotkit?.snap(x, y), [start.x, start.y]).catch(() => {});

    pump = await startPump(page, context, {
      fps,
      quality: spec.quality ?? VIDEO_DEFAULTS.quality,
      frame,
      capture: spec.capture,
      maxFrames: fps * clamp(spec.maxSeconds ?? VIDEO_DEFAULTS.maxSeconds, 1, 600),
      encoder: (size) =>
        startEncoder({ ...size, format, fps, crf: spec.crf, out: ctx.out, ffmpeg: caps.path }),
      log,
    });

    const cursor = makeCursor(page, { ...spec, log, timing, zoom: spec.zoom ?? VIDEO_DEFAULTS.zoom });
    // The cap has to be a timer this take can cancel: an outstanding one would
    // hold the process open long after the file is written.
    let capTimer = null;
    const cap = new Promise((r) => {
      capTimer = setTimeout(() => r("over"), pump.budgetMs);
    });
    const trace = await Promise.race([drive(page, spec, cursor, timing), cap]);
    clearTimeout(capTimer);
    if (trace === "over") log("stopped at --max-seconds; the take is what fit");
    await sleep(timing.tailMs);

    const { frames, width, height } = await pump.stop();
    return {
      path: ctx.out,
      format,
      fps,
      frames,
      width,
      height,
      durationMs: Math.round((frames / fps) * 1000),
      encoder: caps.source,
      capture: pump.mode,
      truncated: trace === "over" || pump.truncated,
      trace: Array.isArray(trace) ? trace : [],
      url: page.url(),
      ms: { total: Date.now() - t0 },
    };
  } finally {
    if (pump) await pump.abort();
    await context.close().catch(() => {});
  }
}

/** The take: lead-in, the actions, and whatever the tail catches. */
async function drive(page, spec, cursor, timing) {
  await sleep(timing.leadInMs);
  return runActions(page, spec.do ?? [], {
    baseUrl: spec.baseUrl,
    timeout: spec.actionTimeout,
    cursor,
  });
}

/* ── The cinematic cursor ───────────────────────────────────────────────────
 * `runActions` calls into this when a recording is running: same verbs, but a
 * pointer that travels, a press that reads, and a camera that can follow.
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * @param {import("playwright").Page} page
 * @param {Record<string, any>} opts
 * @returns {import("./actions.mjs").Cursor}
 */
export function makeCursor(page, opts) {
  const timing = opts.timing ?? TIMING;
  let at = { x: 0, y: 0 };

  /**
   * Where a click on this locator would land, in viewport coordinates.
   *
   * A push-in crops the frame, and the next thing the script asks for may be
   * outside what is left of it — a button at the edge of the card the camera
   * just framed. Pulling back first is what a person would do, and it keeps the
   * press on something the viewer can see.
   */
  async function pointOf(locator, { timeout }) {
    await locator.waitFor({ state: "visible", timeout });
    await locator.scrollIntoViewIfNeeded({ timeout }).catch(() => {});
    let box = await locator.boundingBox({ timeout });
    if (!box) throw new Error("target has no box on screen");
    const frame = page.viewportSize() ?? { width: 1280, height: 800 };
    const outside = (b) =>
      b.x + b.width < 8 || b.y + b.height < 8 || b.x > frame.width - 8 || b.y > frame.height - 8;
    if (outside(box)) {
      await zoomOut();
      box = (await locator.boundingBox({ timeout })) ?? box;
    }
    return { x: box.x + box.width / 2, y: box.y + box.height / 2, box };
  }

  /**
   * Travel there — twice over, and both halves matter.
   *
   * The page animates the drawn pointer along the curve, off its own rAF, so
   * the motion in the file is smooth however the driving process is scheduled.
   * The real mouse walks the same curve more coarsely, because that is what
   * lights up hover states, tooltips and drag affordances on the way — most of
   * what a UI has to say for itself while a pointer crosses it.
   */
  async function glideTo(x, y, ms = timing.moveMs) {
    const from = at;
    const distance = Math.hypot(x - from.x, y - from.y);
    if (distance < 2) {
      at = { x, y };
      return;
    }
    // A short hop should not take as long as a trip across the frame.
    const duration = Math.round(clamp(ms * (0.35 + distance / 900), 140, ms * 1.4));
    await page.evaluate(([px, py, d]) => window.__shotkit?.glide(px, py, d), [x, y, duration]).catch(() => {});
    const steps = Math.max(2, Math.round(duration / 40));
    const startedAt = Date.now();
    for (let i = 1; i <= steps; i++) {
      const p = easeInOut(i / steps);
      await page.mouse.move(from.x + (x - from.x) * p, from.y + (y - from.y) * p);
      const behind = startedAt + (duration * i) / steps - Date.now();
      if (behind > 0) await sleep(behind);
    }
    at = { x, y };
    await sleep(timing.settleMs);
  }

  /**
   * Press and release, and tell the page so it draws it.
   *
   * The overlay listens for real mouse events too, but headless Chromium only
   * flushes those alongside its frames — an animation that has to land on the
   * frame of the press cannot wait for that.
   */
  async function press() {
    await page.evaluate(() => window.__shotkit?.press(true)).catch(() => {});
    await page.mouse.down();
    await sleep(110);
    await page.mouse.up();
    await page.evaluate(() => window.__shotkit?.press(false)).catch(() => {});
  }

  async function camera(z, x, y, ms = timing.zoomMs) {
    const applied = await page
      .evaluate(([zz, xx, yy, mm]) => window.__shotkit?.camera(zz, xx, yy, mm), [z, x, y, ms])
      .catch(() => null);
    await sleep(ms);
    return applied;
  }

  function zoomOut() {
    const size = page.viewportSize() ?? { width: 1280, height: 800 };
    return camera(1, size.width / 2, size.height / 2);
  }

  return {
    typeDelay: timing.typeDelayMs,

    async glide(locator, o = {}) {
      const p = await pointOf(locator, o);
      await glideTo(p.x, p.y);
      return p;
    },

    async click(locator, o = {}) {
      let p = await pointOf(locator, o);
      await glideTo(p.x, p.y);
      if (opts.autoZoom) {
        await camera(opts.zoom, p.x, p.y);
        // The push-in moved the target under the pointer; follow it to where it
        // now is, so the press lands on the thing the viewer is looking at.
        p = await pointOf(locator, o);
        await glideTo(p.x, p.y, timing.moveMs * 0.5);
      }
      await press();
      if (o.dblclick) {
        await sleep(90);
        await press();
      }
      if (opts.autoZoom) {
        // Hold on what the press did, then pull back out — the shape of every
        // demo beat, and the reason auto-zoom does not need a script.
        await sleep(timing.dwellMs);
        await zoomOut();
      }
      return p;
    },

    /**
     * `zoom:out` | `zoom:2` (on the pointer) | `zoom:<sel>[@factor]`.
     * `o.locate` resolves a selector the way the rest of the action list does.
     */
    async zoom(arg, o = {}) {
      const { target, z } = parseZoom(arg, opts.zoom);
      if (z === 1) return zoomOut();
      if (!target) return camera(z, at.x, at.y);
      const p = await pointOf(o.locate(target), o);
      return camera(z, p.x, p.y);
    },

    zoomOut,

    /** A beat after an action, so the viewer sees the result of it. */
    dwell(ms) {
      return sleep(ms ?? timing.dwellMs);
    },
  };
}

/* ── The frame pump ────────────────────────────────────────────────────────
 * Frames arrive when the page changes; the file needs one every 1/fps whether
 * anything changed or not. So the pump holds the newest frame and a
 * self-correcting timer writes it on the beat — a still page costs repeats of
 * one JPEG, and no drift accumulates over a long take.
 * ────────────────────────────────────────────────────────────────────────── */

async function startPump(page, context, opts) {
  const period = 1000 / opts.fps;
  let latest = null;
  let encoder = null;
  let size = { width: 0, height: 0 };
  let stopped = false;
  let truncated = false;
  let timer = null;
  let failure = null;
  let mode = opts.capture === "shots" ? "shots" : "screencast";
  let shooter = null;

  // Nothing in here may throw: it runs on a timer, where a throw is an uncaught
  // exception in whatever process hosts the daemon rather than a failed shot.
  // Anything that goes wrong is held and raised when the take ends.
  const beat = (n, startedAt) => {
    if (stopped) return;
    try {
      if (latest) {
        if (!encoder) {
          size = jpegSize(latest);
          if (!size.width) throw new Error("the first frame was not a readable JPEG");
          encoder = opts.encoder(size);
          opts.log(`encoding ${size.width}x${size.height} @ ${opts.fps}fps`);
        }
        if (encoder.frames >= opts.maxFrames) truncated = true;
        else encoder.write(latest);
      }
    } catch (err) {
      failure ??= err;
    }
    const next = startedAt + (n + 1) * period - Date.now();
    timer = setTimeout(() => beat(n + 1, startedAt), Math.max(0, next));
  };

  if (mode === "screencast") {
    const cdp = await context.newCDPSession(page).catch(() => null);
    if (cdp) {
      cdp.on("Page.screencastFrame", (f) => {
        latest = Buffer.from(f.data, "base64");
        cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
      });
      await cdp.send("Page.startScreencast", {
        format: "jpeg",
        quality: opts.quality,
        maxWidth: Math.round(opts.frame.width * opts.frame.scale),
        maxHeight: Math.round(opts.frame.height * opts.frame.scale),
        everyNthFrame: 1,
      });
      for (let i = 0; i < 40 && !latest; i++) await sleep(50);
      shooter = { stop: () => cdp.send("Page.stopScreencast").catch(() => {}) };
    }
    if (!latest) {
      opts.log("no screencast frames; falling back to a screenshot loop");
      mode = "shots";
      await shooter?.stop();
      shooter = null;
    }
  }

  if (mode === "shots") {
    // Slower and coarser, but it depends on nothing but `page.screenshot`.
    let running = true;
    const loop = (async () => {
      while (running && !stopped) {
        try {
          latest = await page.screenshot({ type: "jpeg", quality: opts.quality, animations: "allow", caret: "hide" });
        } catch {
          if (!stopped) await sleep(100);
        }
      }
    })();
    shooter = {
      stop: async () => {
        running = false;
        await loop.catch(() => {});
      },
    };
    for (let i = 0; i < 60 && !latest; i++) await sleep(50);
  }

  const startedAt = Date.now();
  beat(0, startedAt);

  const halt = async () => {
    if (stopped) return;
    stopped = true;
    if (timer) clearTimeout(timer);
    await shooter?.stop();
  };

  return {
    mode,
    get truncated() {
      return truncated;
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
     * container is not playable.
     */
    async abort() {
      await halt();
      if (!encoder) return;
      await Promise.race([encoder.finish().catch(() => {}), sleep(5_000).then(() => encoder.kill())]);
    },
  };
}
