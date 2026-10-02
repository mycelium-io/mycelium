// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A take on the tech-demo stage: record first, tilt after.
 *
 * Tilting each frame as it arrives would put a render in the pump's beat, and a
 * render is slower than a beat, so the take would stutter or fall behind. So
 * the take is spooled to disk as it is recorded, with the pump none the wiser,
 * and once it ends each frame goes through one held stage page and on to the
 * real encoder. That costs a pass after the take (tens of milliseconds a frame)
 * and buys two things a live tilt could not: frames that are all there, and a
 * camera that can move across the whole take, since its length is known.
 *
 * The pump writes the same buffer on every beat while the page is still, so the
 * spool keeps one file per distinct frame and an index of which beat showed
 * which; with the angle held still, a still stretch is also rendered once.
 */

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { GLASS_FPS, GLASS_VIDEO_STEP } from "./glass.mjs";
import { driftAt, fitScale, stageDocument, tiltTransform, STAGE_DEFAULTS } from "./stage.mjs";

/**
 * An encoder-shaped sink that keeps the take on disk. Same surface the pump
 * drives a real encoder through: `write`, `frames`, `saturated`, `failure`,
 * `finish`.
 */
export function startSpool() {
  const dir = mkdtempSync(join(tmpdir(), "shotkit-take-"));
  /** @type {number[]} which distinct frame each beat showed */
  const order = [];
  let distinct = 0;
  let last = null;
  let failed = null;
  return {
    dir,
    order,
    get frames() {
      return order.length;
    },
    saturated: false,
    get failure() {
      return failed;
    },
    write(buf) {
      if (failed) return false;
      try {
        if (buf !== last) {
          writeFileSync(join(dir, `${distinct}.jpg`), buf);
          distinct += 1;
          last = buf;
        }
        order.push(distinct - 1);
      } catch (err) {
        failed = err;
      }
      return true;
    },
    async finish() {
      if (failed) throw failed;
      if (!order.length) throw new Error("no frames were captured");
      return { frames: order.length };
    },
    read(i) {
      return readFileSync(join(dir, `${i}.jpg`));
    },
    remove() {
      rmSync(dir, { recursive: true, force: true });
    },
  };
}

/** How many frames the intro card adds before the take's first frame. */
export function titleFrames(o, fps) {
  return o.intro ? Math.round((o.titleSeconds ?? 2.6) * fps) : 0;
}

/**
 * Where each click and keystroke falls in the finished video, written beside
 * it as `<video>.sounds.json` for a sound pass: `{t, kind}` in seconds, and for
 * typing `{t, t1, kind: "type", chars}`, the span the characters went in over.
 *
 * @param {string} out the video's path
 * @param {{beat:number, kind:string, [k:string]:unknown}[]} sounds by take beat
 */
export function writeSounds(out, sounds, fps, intro) {
  const at = (beat) => Number(((intro + beat) / fps).toFixed(3));
  const events = sounds.map(({ beat, end, ...rest }) => ({
    t: at(beat),
    ...(typeof end === "number" ? { t1: at(end) } : {}),
    ...rest,
  }));
  writeFileSync(`${out}.sounds.json`, JSON.stringify({ fps, events }, null, 1));
}

/**
 * Put every spooled frame on the stage and encode the result.
 *
 * @param {import("./engine.mjs").Engine} eng
 * @param {ReturnType<typeof startSpool>} spool
 * @param {{stage: Record<string, any>, drift: number, theme: "dark"|"light", art?: string,
 *          live?: string, fps?: number, captions?: {beat:number, text:string}[],
 *          words?: import("./stage.mjs").StageWords, intro?: string, outro?: string, titleSeconds?: number,
 *          frameWidth: number, frameHeight: number, quality?: number,
 *          encoder: (size: {width:number, height:number}) => any,
 *          log?: (m: string) => void}} o
 * @returns {Promise<{frames:number, width:number, height:number, rendered:number}>}
 */
export async function restage(eng, spool, o) {
  const log = o.log ?? (() => {});
  const width = o.stage.width ?? STAGE_DEFAULTS.width;
  const height = o.stage.height ?? STAGE_DEFAULTS.height;
  const layout = { ...o.stage, imgWidth: o.frameWidth, imgHeight: o.frameHeight };
  const k = fitScale(layout);

  // A render is one beat's distinct (frame, angle) pair; consecutive beats that
  // share one share the render. With the angle held, a still stretch is one.
  // A live scene under the window moves on every beat, so no two beats share
  // a render; it is seeked to the beat's time on the scene's own clock.
  const live = Boolean(o.live);
  const fps = o.fps ?? 30;
  // Title cards are beats of their own before and after the take, with the
  // window faded out under them; the take's first and last frames hold there.
  const titleBeats = Math.round((o.titleSeconds ?? 2.6) * fps);
  const fade = Math.max(1, Math.round(fps * 0.45));
  const introN = titleFrames(o, fps);
  const outroN = o.outro ? titleBeats : 0;
  const take = spool.order.length;
  const total = introN + take + outroN;
  const captions = [...(o.captions ?? [])].sort((a, b) => a.beat - b.beat);

  /** The caption a take beat shows: the old words fade out, then the new fade in. */
  const captionAt = (t) => {
    let c = -1;
    while (c + 1 < captions.length && captions[c + 1].beat <= t) c += 1;
    if (c < 0) return { text: "", alpha: 0 };
    const since = t - captions[c].beat;
    const prev = c > 0 ? captions[c - 1].text : "";
    if (prev && since < fade) return { text: prev, alpha: 1 - since / fade };
    const start = prev ? fade : 0;
    return { text: captions[c].text, alpha: captions[c].text ? Math.min(1, Math.max(0, (since - start) / fade)) : 0 };
  };
  const ease = (x) => x * x * (3 - 2 * x);

  /** @type {{frame:number, transform:string, scene?:number, view?:any}[]} */
  const renders = [];
  /** @type {number[]} which render each beat shows */
  const beats = [];
  let prevKey = null;
  for (let i = 0; i < total; i++) {
    const t = Math.min(take - 1, Math.max(0, i - introN));
    const frame = spool.order[t];
    const { tilt, zoom } = driftAt(o.stage.tilt, o.drift, total > 1 ? i / (total - 1) : 0);
    const transform = tiltTransform(tilt, k * zoom, o.stage.perspective);
    const scene = live
      ? Math.round(((i / fps) * GLASS_FPS) / GLASS_VIDEO_STEP) * GLASS_VIDEO_STEP
      : undefined;
    let view;
    if (o.words) {
      // Into the take: the title fades out as the window fades in, and the
      // reverse into the outro.
      let win = 1;
      let title = { text: "", alpha: 0 };
      if (i < introN) {
        const k2 = ease(Math.min(1, Math.max(0, (introN - i) / fade)));
        title = { text: o.intro ?? "", alpha: k2 };
        win = 1 - k2;
      } else if (i >= introN + take) {
        const k2 = ease(Math.min(1, (i - introN - take + 1) / fade));
        title = { text: o.outro ?? "", alpha: k2 };
        win = 1 - k2;
      }
      const cap = i >= introN && i < introN + take ? captionAt(t) : { text: "", alpha: 0 };
      const r = (n) => Math.round(n * 1000) / 1000;
      view = { cap: { text: cap.text, alpha: r(cap.alpha) }, title: { text: title.text, alpha: r(title.alpha) }, win: r(win) };
    }
    const key = `${frame}|${transform}|${scene}|${JSON.stringify(view)}`;
    if (key !== prevKey) renders.push({ frame, transform, scene, view });
    prevKey = key;
    beats.push(renders.length - 1);
  }

  // Several stage pages rendering side by side: a render is mostly waiting on
  // the compositor and the JPEG encoder, which a single page leaves idle.
  const first = await eng.staticPage({ width, height, scale: 1, theme: o.theme });
  const pages = [first];
  for (let i = 1; i < Math.min(RESTAGE_PAGES, renders.length); i++) pages.push(await first.context().newPage());
  const doc = stageDocument({ ...layout, frame: "window", theme: o.theme, art: o.art, live: o.live, words: o.words });
  await Promise.all(pages.map((p) => p.setContent(doc, { waitUntil: "load" })));
  // A webfont loads when first used, which would be a frame or two of the
  // fallback face; load every face the stylesheet declares before frame one.
  await Promise.all(pages.map((p) => p.evaluate(() =>
    Promise.all([...document.fonts].map((f) => f.load().catch(() => {}))).then(() => document.fonts.ready))));
  // A clipped page screenshot rather than a locator's: the stage fills the page
  // exactly, and the locator's visibility and stability checks are a cost paid
  // on every frame for nothing.
  const shoot = { type: /** @type {"jpeg"} */ ("jpeg"), quality: o.quality ?? 92, clip: { x: 0, y: 0, width, height } };
  const render = async (p, r) => {
    const src = `data:image/jpeg;base64,${spool.read(r.frame).toString("base64")}`;
    await p.evaluate(([s, tr, sc, v]) => window.__stage.set(s, tr, sc, v), [src, r.transform, r.scene, r.view]);
    return p.screenshot(shoot);
  };

  const encoder = o.encoder({ width, height });
  let beat = 0;
  let lastLog = Date.now();
  try {
    for (let start = 0; start < renders.length; start += pages.length) {
      const batch = renders.slice(start, start + pages.length);
      const bufs = await Promise.all(batch.map((r, j) => render(pages[j], r)));
      // Write every beat whose render is now in hand, in order.
      while (beat < total && beats[beat] < start + batch.length) {
        if (!encoder.write(bufs[beats[beat] - start])) await drained(encoder);
        if (encoder.failure) throw encoder.failure;
        beat += 1;
      }
      if (Date.now() - lastLog > 2000) {
        log(`staging ${beat}/${total}`);
        lastLog = Date.now();
      }
    }
    await encoder.finish();
  } catch (err) {
    await encoder.finish(5_000).catch(() => {});
    throw err;
  } finally {
    await Promise.all(pages.slice(1).map((p) => p.close().catch(() => {})));
  }
  return { frames: total, width, height, rendered: renders.length };
}

/** Stage pages rendering at once. Past four, they mostly queue on one GPU process. */
const RESTAGE_PAGES = 4;

/** Wait for an encoder that reported backpressure to catch up. */
async function drained(encoder) {
  for (let i = 0; i < 400 && encoder.saturated && !encoder.failure; i++) {
    await new Promise((r) => setTimeout(r, 5));
  }
}
