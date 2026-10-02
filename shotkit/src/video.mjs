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
 * Four pieces, kept apart on purpose:
 *
 *   cursor.mjs   what the page draws (pointer, ripple, camera transform)
 *   this file    the take: the cinematic reading of an action list
 *   pump.mjs     frames out of the page, on a clock
 *   encode.mjs   frames to a file
 *
 * The action vocabulary is the one `--do` already speaks. A recording does not
 * get its own script format: `click:Negotiate` is a click in a screenshot and a
 * glide-press-settle in a take, because the difference between those is the
 * recorder's business and not the caller's.
 */

import { readFile } from "node:fs/promises";
import { extname } from "node:path";
import { OVERLAY_DEFAULTS, installOverlay } from "./cursor.mjs";
import { defaultFormat, findEncoder, startEncoder } from "./encode.mjs";
import { frameOf, policyOf, preparePage, seedStorage } from "./engine.mjs";
import { runActions } from "./actions.mjs";
import { MAX_SPEED, frameSource, startPump } from "./pump.mjs";
import { palette } from "./theme.mjs";
import { isStaged, pickStage } from "./stage.mjs";
import { restage, startSpool, titleFrames, writeSounds } from "./restage.mjs";
import { STAGE_STYLE } from "./project.mjs";

/** Timing, in ms. Beats a viewer can follow rather than the fastest that works. */
export const TIMING = {
  moveMs: 620,
  dwellMs: 620,
  zoomMs: 620,
  leadInMs: 500,
  tailMs: 1000,
  typeDelayMs: 55,
  settleMs: 130,
  pressMs: 110,
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
    ...(spec.pressMs !== undefined ? { pressMs: spec.pressMs } : {}),
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
    ...(spec.captionAt === "top" ? { captionAt: "top" } : {}),
  });
  if (spec.storage) await seedStorage(context, spec.storage);

  const t0 = Date.now();
  const page = await context.newPage();
  let pump = null;
  let capTimer = null;
  /** @type {ReturnType<typeof startSpool> | null} */
  let spool = null;
  try {
    await page.goto(spec.url, { waitUntil: spec.waitUntil ?? "domcontentloaded", timeout: spec.timeout ?? 30_000 });
    // Waits, hidden selectors and extra CSS, but not the actions: those are the
    // take, and they have to happen with the camera rolling.
    await preparePage(page, { ...spec, do: [] });
    await page.mouse.move(start.x, start.y);
    await page.evaluate(([x, y]) => window.__shotkit?.snap(x, y), [start.x, start.y]).catch(() => {});

    const source = await frameSource(page, context, {
      capture: spec.capture,
      quality: spec.quality ?? VIDEO_DEFAULTS.quality,
      frame,
      log,
    });
    const encode = (size) => startEncoder({ ...size, format, fps, crf: spec.crf, out: ctx.out, ffmpeg: caps.path });
    // On a stage the take goes to a spool, and is tilted and encoded after it
    // ends (restage.mjs); the pump drives either the same way.
    const staged = isStaged(spec);
    pump = startPump({
      source,
      fps,
      maxFrames: fps * clamp(spec.maxSeconds ?? VIDEO_DEFAULTS.maxSeconds, 1, 600),
      encoder: staged ? () => (spool = startSpool()) : encode,
      log,
    });

    /** @type {{beat:number, text:string}[] | undefined} */
    const captions = staged ? [] : undefined;
    /** Clicks and keystrokes, by the take beat they happen on, for a sound pass. */
    /** @type {{beat:number, kind:string, [k:string]:unknown}[] | undefined} */
    const sounds = staged ? [] : undefined;
    const cursor = makeCursor(page, {
      ...spec,
      log,
      timing,
      zoom: spec.zoom ?? VIDEO_DEFAULTS.zoom,
      pump,
      captions,
      sounds,
      beat: () => spool?.frames ?? 0,
    });
    // Three ways a take ends: the flow finishes, the video reaches --max-seconds
    // (the pump says so), or there is nothing left to record into. A sped-up
    // take can run far longer than the video it makes, so the wall clock is
    // only a runaway guard, at the top speed. It is a timer this take can
    // cancel — an outstanding one holds the process open long after the file is
    // written, so it is cleared in the `finally` below, on the throwing path too.
    const cap = new Promise((r) => {
      capTimer = setTimeout(() => r("over"), pump.budgetMs * MAX_SPEED);
    });
    const flow = drive(page, spec, cursor, timing, log);
    // When the cap or a dead encoder wins the race the flow is still running,
    // and will fail into nobody's hands once the context closes under it. That
    // rejection is this take's business, not the process's.
    flow.catch(() => {});
    const trace = await Promise.race([flow, cap, pump.trouble]);
    if (trace === "over") log("stopped at --max-seconds; the take is what fit");
    if (trace === "encoder") log("the encoder stopped; ending the take");
    await sleep(timing.tailMs);

    let { frames, width, height } = await pump.stop();
    const url = page.url();
    const tStage = Date.now();
    let staging;
    if (spool) {
      // The take is over: its page has nothing left to show, and would only
      // compete with the staging pass for the CPU.
      await context.close().catch(() => {});
      const stage = pickStage(spec);
      const result = await restage(eng, spool, {
        stage,
        drift: spec.drift ?? STAGE_DRIFT,
        theme: spec.theme ?? "dark",
        art: ctx.stageArt,
        live: ctx.stageLive,
        fps,
        captions,
        words: await stageWords(spec),
        intro: spec.intro,
        outro: spec.outro,
        titleSeconds: spec.titleSeconds,
        frameWidth: Math.round(width / frame.scale),
        frameHeight: Math.round(height / frame.scale),
        quality: spec.quality ?? VIDEO_DEFAULTS.quality,
        encoder: encode,
        log,
      });
      ({ width, height, frames } = result);
      staging = { tilt: stage.tilt, drift: spec.drift ?? STAGE_DRIFT, rendered: result.rendered, ms: Date.now() - tStage };
      if (sounds?.length) writeSounds(ctx.out, sounds, fps, titleFrames(spec, fps));
    }
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
      url,
      ...(staging ? { stage: staging } : {}),
      ms: { total: Date.now() - t0, ...(staging ? { stage: staging.ms } : {}) },
    };
  } finally {
    clearTimeout(capTimer);
    if (pump) await pump.abort();
    spool?.remove();
    await context.close().catch(() => {});
  }
}

/**
 * How the stage draws a take's words, from the project's `stage` config: the
 * faces, the accent, and the logo the title cards carry.
 * @param {Record<string, any>} spec
 */
async function stageWords(spec) {
  const logo = STAGE_STYLE.logo
    ? `data:image/${extname(STAGE_STYLE.logo).slice(1).replace("jpg", "jpeg").replace("svg", "svg+xml")};base64,` +
      (await readFile(STAGE_STYLE.logo)).toString("base64")
    : undefined;
  return {
    ...(STAGE_STYLE.fonts ? { fonts: STAGE_STYLE.fonts } : {}),
    ...(STAGE_STYLE.titleFont ? { titleFont: STAGE_STYLE.titleFont } : {}),
    ...(STAGE_STYLE.titleStyle ? { titleStyle: STAGE_STYLE.titleStyle } : {}),
    ...(STAGE_STYLE.textFont ? { textFont: STAGE_STYLE.textFont } : {}),
    ...(STAGE_STYLE.accent ? { accent: STAGE_STYLE.accent } : {}),
    ...(logo ? { logo } : {}),
    at: spec.captionAt === "top" ? "top" : "bottom",
  };
}

/** Degrees a staged take swings across its length unless `--drift` says otherwise. */
export const STAGE_DRIFT = 10;

/** The take: lead-in, the actions, and whatever the tail catches. */
async function drive(page, spec, cursor, timing, log) {
  await sleep(timing.leadInMs);
  return runActions(page, spec.do ?? [], {
    baseUrl: spec.baseUrl,
    timeout: spec.actionTimeout,
    cursor,
    log,
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
    opts.sounds?.push({ beat: opts.beat(), kind: "click" });
    await page.evaluate(() => window.__shotkit?.press(true)).catch(() => {});
    await page.mouse.down();
    await sleep(timing.pressMs);
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

    /**
     * Type `text` with `type`, noting the span it went in over for a sound pass.
     * @param {(text: string) => Promise<void>} type
     */
    async typing(text, type) {
      const beat = opts.beat();
      await type(text);
      opts.sounds?.push({ beat, end: opts.beat(), kind: "type", chars: [...text].length });
    },

    /** A key pressed on its own, like Enter, for a sound pass. */
    key(name) {
      opts.sounds?.push({ beat: opts.beat(), kind: "key", key: name });
    },

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
     * `o.locate` resolves a selector the way the rest of the action list does,
     * which includes asking the page whether a bare word is a label or a tag.
     */
    async zoom(arg, o = {}) {
      const { target, z } = parseZoom(arg, opts.zoom);
      if (z === 1) return zoomOut();
      if (!target) return camera(z, at.x, at.y);
      const p = await pointOf(await o.locate(target), o);
      return camera(z, p.x, p.y);
    },

    zoomOut,

    /** A beat after an action, so the viewer sees the result of it. */
    dwell(ms) {
      return sleep(ms ?? timing.dwellMs);
    },

    /** Put a lower-third caption up, or take it down with an empty one. */
    async caption(text) {
      // On a stage the caption belongs to the stage, not the page: it is noted
      // against the beat it starts on and drawn flat over the tilted window
      // when the take is staged.
      if (opts.captions) {
        opts.captions.push({ beat: opts.beat(), text: String(text ?? "") });
        return;
      }
      await page.evaluate((t) => window.__shotkit?.caption(t), text).catch(() => {});
    },

    /**
     * Time-lapse from here: `speed:4` plays what follows four times faster,
     * `speed:1` goes back to real time. For the stretches a viewer shouldn't
     * sit through, like a model thinking, with the page still live throughout.
     */
    speed(n) {
      opts.pump?.setSpeed(n);
      opts.log?.(`speed ${opts.pump?.speed ?? 1}x`);
    },
  };
}
