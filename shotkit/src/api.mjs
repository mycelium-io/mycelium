// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The one API. Every entry point — the `shot` CLI, the daemon, an import from a
 * script — comes through `capture(spec)`, so there is a single place where a
 * shot is defined and a single result shape to consume.
 *
 *   import { capture } from "../shotkit/src/api.mjs";
 *   const r = await capture({ op: "term", argv: ["mycelium", "--help"] });
 *   const s = await capture({ op: "app", route: "/", responsive: true, sheet: true });
 *
 * `capture` is transport-agnostic on purpose: the daemon calls it in-process
 * after deserializing a socket request, and `--no-daemon` calls it directly.
 */

import { readFile } from "node:fs/promises";
import { basename, resolve } from "node:path";
import { Engine, REPO_ROOT, pngSize, writeShot } from "./engine.mjs";
import { codeDocument } from "./code.mjs";
import { terminalDocument } from "./terminal.mjs";
import { cardDocument, imageCardDocument } from "./card.mjs";
import { sheetDocument } from "./sheet.mjs";
import { resolveBaseUrl } from "./app.mjs";
import { runCommand } from "./run.mjs";
import { stripAnsi } from "./ansi.mjs";
import { viewportList } from "./viewports.mjs";
import { record, resolveFormat } from "./video.mjs";

/**
 * @typedef {object} PageSpec
 * @property {string} [url] for `op: "url"`
 * @property {string} [route] for `op: "app"`
 * @property {string} [baseUrl] app origin; probed when absent
 * @property {boolean} [mock] boot `pnpm dev:mock` and hold it in the daemon
 * @property {number} [width] @property {number} [height] @property {number} [scale]
 * @property {string} [viewport] preset name or `1280x800@2`
 * @property {string} [viewports] comma-separated presets — one shot each
 * @property {boolean} [responsive] shorthand for the standard breakpoint ladder
 * @property {boolean} [sheet] compose the frames into one contact sheet
 * @property {"dark"|"light"} [theme]
 * @property {boolean} [fullPage] @property {string} [element] clip selector
 * @property {string} [waitFor] @property {string} [waitForText]
 * @property {"none"|"fast"|"full"} [settle]
 * @property {string[]} [do] ordered navigation actions, see actions.mjs
 * @property {string[]} [hide] @property {string[]} [mask] @property {string} [css]
 * @property {number} [delay] @property {Record<string,string>} [storage]
 * @property {number} [timeout] @property {"png"|"jpeg"} [format] @property {number} [quality]
 * @property {boolean} [transparent]
 * @property {boolean} [chrome] wrap the capture in browser window chrome
 * @property {string} [address] address-bar text when `chrome` is set
 * @property {"dark"|"light"} [chromeTheme] frame theme, when it should differ
 *   from the app's — a light frame around a dark app, say
 * @property {number} [fps] `op: "video"` — frames per second (default 30)
 * @property {number} [zoom] push-in factor for `zoom:` and `--auto-zoom`
 * @property {boolean} [autoZoom] push in on every click, and back out after
 */

export const DEFAULT_OUT_DIR = process.env.SHOTKIT_OUT ?? resolve(REPO_ROOT, ".shotkit");

const slug = (s) =>
  (s || "shot").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "shot";

const stamp = () => new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "-");

/** The extension a spec's output wants: an image format, or a video container. */
function outputExt(spec) {
  if (spec.op === "video") return spec.format ?? "webm";
  return spec.format === "jpeg" ? "jpg" : "png";
}

/** Where this shot lands, given `--out` / `--out-dir` / `--name` / `--unique`. */
function outputPath(spec, fallbackName, suffix = "") {
  const ext = outputExt(spec);
  if (spec.out && !suffix) return resolve(spec.out);
  if (spec.out) {
    const base = resolve(spec.out).replace(/\.(png|jpg|jpeg|mp4|webm|gif)$/i, "");
    return `${base}${suffix}.${ext}`;
  }
  const dir = spec.outDir ? resolve(spec.outDir) : DEFAULT_OUT_DIR;
  const name = slug(spec.name ?? fallbackName);
  return resolve(dir, `${name}${suffix}${spec.unique ? `-${stamp()}` : ""}.${ext}`);
}

/** A process-wide engine, so an in-process caller warms up the same way. */
let sharedEngine = null;
export function engine() {
  if (!sharedEngine) sharedEngine = new Engine();
  return sharedEngine;
}
export async function shutdown() {
  if (sharedEngine) await sharedEngine.close();
  sharedEngine = null;
}

const CARD_KEYS = ["theme", "backdrop", "padding", "radius", "shadow", "window", "title", "fontSize", "lineHeight", "font", "cols", "maxWidth"];
const pickCard = (spec) => Object.fromEntries(CARD_KEYS.filter((k) => spec[k] !== undefined).map((k) => [k, spec[k]]));
const pickStatic = (spec) => ({
  theme: spec.theme,
  scale: spec.scale,
  format: spec.format,
  quality: spec.quality,
  transparent: spec.transparent ?? spec.backdrop === "none",
});

/**
 * Run one shot (or one responsive set).
 * @param {Record<string, any>} spec
 * @param {{log?: (m:string)=>void, mode?: string}} [ctx]
 */
export async function capture(spec, ctx = {}) {
  const log = ctx.log ?? (() => {});
  const t0 = Date.now();
  const eng = engine();
  const base = { ok: true, op: spec.op, mode: ctx.mode ?? "direct", engine: eng.channel };

  if (spec.op === "term" || spec.op === "code" || spec.op === "html") {
    const { buf, meta, timings, fallbackName } = await renderCard(spec, eng);
    return finish({ ...base, meta, ms: { total: Date.now() - t0, ...timings } }, spec, buf, fallbackName);
  }

  if (spec.op === "video") {
    const { url, baseUrl } = await resolvePageUrl({ ...spec, op: spec.url ? "url" : "app" }, log);
    const { format } = await resolveFormat(spec);
    const frame = viewportList(spec)[0];
    const isApp = Boolean(spec.route);
    const name = `video-${slug(spec.route ?? new URL(url).pathname)}`;
    const out = outputPath({ ...spec, format }, name);
    const take = await record(
      eng,
      {
        ...spec,
        // A preset's own pixel ratio is for stills; a take is a viewport-sized
        // file unless --scale asks for more, since doubling it doubles every
        // frame for detail a video does not keep.
        ...(frame ? { width: frame.viewport.width, height: frame.viewport.height } : {}),
        format,
        url,
        baseUrl,
        settle: spec.settle ?? (isApp ? "fast" : "none"),
        storage: themedStorage(spec, isApp),
      },
      { log, out },
    );
    // Everything about *how* the take was made is meta; the file and its shape
    // stay at the top level, where every other op puts them.
    const { capture: source, encoder, truncated, ...rest } = take;
    const result = {
      ...base,
      ...rest,
      meta: { url, baseUrl, viewport: frame?.name, capture: source, encoder, truncated },
      ms: { total: Date.now() - t0, ...take.ms },
    };
    if (!spec.stdout) return result;
    const bytes = await readFile(take.path);
    return { ...result, base64: bytes.toString("base64"), bytes: bytes.length };
  }

  if (spec.op === "url" || spec.op === "app") {
    const { url, baseUrl } = await resolvePageUrl(spec, log);
    const fallbackName = spec.op === "app" ? `app-${slug(spec.route ?? "home")}` : `url-${slug(new URL(url).pathname)}`;
    const pageSpec = {
      ...spec,
      url,
      baseUrl,
      settle: spec.settle ?? (spec.op === "app" ? "fast" : "none"),
      storage: themedStorage(spec),
    };
    const frames = viewportList(spec);

    if (frames.length <= 1) {
      const frame = frames[0]?.viewport;
      const tCap = Date.now();
      const raw = await eng.capturePage({ ...pageSpec, ...(frame ?? {}) });
      const buf = await wrapChrome(eng, raw.buf, spec, prettyAddress(spec, url));
      const meta = { url, baseUrl, viewport: frames[0]?.name, trace: raw.trace, chrome: Boolean(spec.chrome) };
      return finish(
        { ...base, meta, ms: { total: Date.now() - t0, capture: Date.now() - tCap } },
        spec,
        buf,
        fallbackName,
      );
    }
    return captureResponsive({ base, spec, pageSpec, frames, fallbackName, eng, t0, url, baseUrl });
  }

  throw new Error(`unknown op: ${spec.op}`);
}

/**
 * Seed the app's own theme alongside the browser's.
 *
 * `colorScheme` on the context only sets the `prefers-color-scheme` media query,
 * and the frontend does not follow it: next-themes reads `localStorage.theme`
 * before first paint and wins. So `--theme light` has to write that key too,
 * or it produces a light frame around an unchanged dark app. An explicit
 * `--storage theme=…` still takes precedence.
 */
function themedStorage(spec, isApp = spec.op === "app") {
  if (!isApp) return spec.storage;
  return { theme: spec.theme ?? "dark", ...(spec.storage ?? {}) };
}

/**
 * Optionally re-shoot a page capture inside browser chrome.
 *
 * Runs the capture back through the card renderer, so a framed app screenshot
 * and a framed terminal card come out of one code path and match each other.
 * @param {any} eng @param {Buffer} buf @param {Record<string,any>} spec
 */
async function wrapChrome(eng, buf, spec, address) {
  if (!spec.chrome) return buf;
  const scale = spec.scale ?? 2;
  const { width } = pngSize(buf);
  const html = imageCardDocument(buf.toString("base64"), Math.round(width / scale), {
    ...pickCard(spec),
    theme: spec.chromeTheme ?? spec.theme ?? "dark",
    address: spec.address ?? address,
  });
  // Same scale as the capture, so one image pixel lands on one device pixel.
  return eng.captureStatic({
    html,
    ...pickStatic(spec),
    theme: spec.chromeTheme ?? spec.theme ?? "dark",
    scale,
    width: 2600,
    height: 2000,
  });
}

/** app/url/session ops all need to know where the app is. */
async function resolvePageUrl(spec, log) {
  if (spec.op === "url" || spec.url?.startsWith("http")) return { url: spec.url, baseUrl: undefined };
  const baseUrl = await resolveBaseUrl({ baseUrl: spec.baseUrl, mock: spec.mock, log });
  const route = spec.route ?? "/";
  return { url: `${baseUrl}${route.startsWith("/") ? route : `/${route}`}`, baseUrl };
}

/** One page, every requested breakpoint, optionally composed into a sheet. */
async function captureResponsive({ base, spec, pageSpec, frames, fallbackName, eng, t0, url, baseUrl }) {
  const shots = [];
  const composed = [];
  for (const { name, viewport } of frames) {
    const tCap = Date.now();
    const raw = await eng.capturePage({ ...pageSpec, ...viewport });
    const buf = await wrapChrome(eng, raw.buf, { ...spec, scale: viewport.scale }, prettyAddress(spec, url));
    const size = pngSize(buf);
    composed.push({ label: viewport.label ?? name, base64: buf.toString("base64"), ...size, scale: viewport.scale });
    if (!spec.sheetOnly) {
      const written = await writeShot(outputPath(spec, fallbackName, `-${name}`), buf);
      shots.push({ viewport: name, ...written, ms: Date.now() - tCap });
    } else {
      shots.push({ viewport: name, ...size, ms: Date.now() - tCap });
    }
  }

  const result = {
    ...base,
    meta: { url, baseUrl, viewports: frames.map((f) => f.name) },
    shots,
    ms: { total: Date.now() - t0 },
  };

  if (!spec.sheet) return result;
  const html = sheetDocument(composed, {
    theme: spec.theme ?? "dark",
    backdrop: spec.backdrop,
    title: spec.sheetTitle ?? `${spec.route ?? url} — ${frames.map((f) => f.name).join(" · ")}`,
  });
  const buf = await eng.captureStatic({ html, ...pickStatic(spec), scale: 1, width: 2600, height: 2000 });
  const written = await writeShot(outputPath(spec, `${fallbackName}-sheet`), buf);
  return { ...result, ...written, sheet: written.path, ms: { total: Date.now() - t0 } };
}

/** term / code / html all end in one static render. */
async function renderCard(spec, eng) {
  const timings = {};
  /** @type {Record<string, any>} */
  const meta = {};
  let html;
  let selector;
  let fallbackName;

  if (spec.op === "term") {
    let output = spec.text;
    let command = spec.command;
    if (output === undefined) {
      const tRun = Date.now();
      const run = await runCommand({
        argv: spec.argv,
        cwd: spec.cwd,
        cols: spec.cols ?? 100,
        timeout: spec.commandTimeout,
        env: spec.env,
        pty: spec.pty,
      });
      timings.command = Date.now() - tRun;
      output = run.output;
      command = command ?? run.command;
      meta.exitCode = run.exitCode;
      meta.pty = run.pty;
      if (run.timedOut) meta.timedOut = true;
      if (spec.echo) meta.plain = stripAnsi(output);
    }
    const doc = terminalDocument({
      ...pickCard(spec),
      output,
      command: spec.prompt === false ? undefined : command,
      prompt: typeof spec.prompt === "string" ? spec.prompt : undefined,
      exitCode: meta.exitCode,
      showExit: spec.showExit !== false,
      title: spec.title ?? (spec.argv ? spec.argv[0] : "terminal"),
    });
    html = doc.html;
    meta.rows = doc.rows;
    meta.cols = doc.cols;
    fallbackName = `term-${slug(command ?? "text")}`;
  } else if (spec.op === "code") {
    const doc = await codeDocument({ ...pickCard(spec), ...pickCode(spec) });
    html = doc.html;
    meta.lang = doc.lang;
    meta.rows = doc.rows;
    fallbackName = `code-${slug(spec.file ? basename(spec.file) : (spec.lang ?? "snippet"))}`;
  } else {
    const source = spec.html ?? (await readFile(resolve(spec.file), "utf8"));
    html = spec.raw === false ? cardDocument(source, pickCard(spec)) : source;
    selector = spec.element ?? (html.includes('id="canvas"') ? "#canvas" : "body");
    fallbackName = spec.file ? `html-${slug(basename(spec.file))}` : "html";
  }

  const tCap = Date.now();
  const buf = await eng.captureStatic({ html, selector, ...pickStatic(spec) });
  timings.capture = Date.now() - tCap;
  return { buf, meta, timings, fallbackName };
}

/**
 * What goes in the address bar. A docs screenshot reads better showing the route
 * than `localhost:41973`, which is an artifact of how the shot was taken.
 */
function prettyAddress(spec, url) {
  if (spec.op === "app" && spec.route) return spec.route;
  return url;
}

const pickCode = (spec) => ({
  code: spec.code,
  file: spec.file,
  lang: spec.lang,
  lineNumbers: spec.lineNumbers,
  startLine: spec.startLine,
  highlight: spec.highlight,
  range: spec.range,
});

/** Either hand the bytes back, or put them on disk and hand back the path. */
async function finish(result, spec, buf, fallbackName) {
  if (spec.stdout) return { ...result, base64: buf.toString("base64"), bytes: buf.length, ...pngSize(buf) };
  const written = await writeShot(outputPath(spec, fallbackName), buf);
  return { ...result, ...written };
}

/* ── Held pages ─────────────────────────────────────────────────────────────
 * A session is a page the daemon keeps open under a name. It exists because a
 * screenshot three clicks into a flow is otherwise a cold load plus a replay of
 * every click, every time — and because an agent driving a UI wants to look,
 * decide, then act, which is a conversation with one page rather than a batch.
 * ────────────────────────────────────────────────────────────────────────── */

/** @param {Record<string, any>} spec */
export async function session(spec, ctx = {}) {
  const log = ctx.log ?? (() => {});
  const eng = engine();
  const name = spec.session ?? "default";
  const t0 = Date.now();

  if (spec.op === "open") {
    const { url, baseUrl } = await resolvePageUrl({ ...spec, op: spec.url ? "url" : "app" }, log);
    const frame = viewportList(spec)[0]?.viewport;
    const meta = await eng.openSession(name, { ...spec, ...(frame ?? {}), url, baseUrl, settle: spec.settle ?? "fast" });
    return { ok: true, op: "open", session: meta, ms: { total: Date.now() - t0 } };
  }
  if (spec.op === "act") {
    const { trace, meta } = await eng.actOnSession(name, spec);
    return { ok: true, op: "act", session: meta, trace, ms: { total: Date.now() - t0 } };
  }
  if (spec.op === "resize") {
    const frame = viewportList(spec)[0]?.viewport;
    if (!frame) throw new Error("resize needs --viewport");
    const meta = await eng.resizeSession(name, frame);
    return { ok: true, op: "resize", session: meta, ms: { total: Date.now() - t0 } };
  }
  if (spec.op === "shoot") {
    const shot = await eng.shootSession(name, spec);
    const { trace, meta } = shot;
    const buf = await wrapChrome(eng, shot.buf, spec, spec.address ?? meta.url);
    const result = { ok: true, op: "shoot", session: meta, trace, mode: ctx.mode ?? "direct", ms: { total: Date.now() - t0 } };
    return finish(result, spec, buf, `session-${slug(name)}`);
  }
  if (spec.op === "close") {
    const closed = await eng.closeSession(name);
    return { ok: true, op: "close", closed, session: { name } };
  }
  if (spec.op === "sessions") {
    return { ok: true, op: "sessions", sessions: eng.listSessions() };
  }
  throw new Error(`unknown session op: ${spec.op}`);
}

export const SESSION_OPS = new Set(["open", "act", "resize", "shoot", "close", "sessions"]);
