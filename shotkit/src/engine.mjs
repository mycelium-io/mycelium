// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The capture engine: one browser, pooled contexts, and the three things a
 * caller can ask for — a card, a one-shot page, or a page held open.
 *
 * Everything here is written to be *held*. The engine is a long-lived object the
 * daemon keeps between requests, so the costs that dominate a naive screenshot
 * script — launching Chromium, opening a context, loading fonts — are paid once
 * and amortized over every later shot. `--no-daemon` runs the same code with a
 * lifetime of one capture, which is why a cold shot is slow and a warm one is
 * not.
 *
 * Card renders reuse a single page per pool key and only swap its content:
 * no navigation, no network, so the marginal cost is a layout and a rasterize.
 * Sessions go further and hold the page itself, which is what makes a multi-step
 * flow cheap — the alternative is replaying every click from a cold load before
 * each shot in the sequence.
 */

import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { launchChromium } from "./browser.mjs";
import { runActions } from "./actions.mjs";
import { policyArgs, policyKey } from "./network.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
export const SHOTKIT_ROOT = resolve(HERE, "..");
export const REPO_ROOT = resolve(SHOTKIT_ROOT, "..");

/**
 * Playwright is resolved rather than plainly imported: a checkout that has run
 * `pnpm install` in mycelium-frontend already has a matching copy, and borrowing
 * it means `shotkit/` needs no install of its own.
 */
export async function loadPlaywright() {
  const require_ = createRequire(import.meta.url);
  const candidates = ["playwright", resolve(REPO_ROOT, "mycelium-frontend/node_modules/playwright/index.js")];
  for (const spec of candidates) {
    try {
      const path = spec.startsWith("/") ? spec : require_.resolve(spec);
      const mod = await import(`file://${path}`);
      // Playwright is CommonJS: the ESM namespace of a CJS module carries the
      // exports object on `default`, and only sometimes re-exports its keys.
      return mod.chromium ? mod : (mod.default ?? mod);
    } catch {
      // try the next candidate
    }
  }
  throw new Error("playwright not found. Run `npm install` in shotkit/, or `pnpm install` in mycelium-frontend/.");
}

/** Width/height straight out of the PNG IHDR — cheaper than decoding. */
export function pngSize(buf) {
  if (buf.length < 24 || buf.readUInt32BE(0) !== 0x89504e47) return { width: 0, height: 0 };
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

const LAUNCH_ARGS = [
  "--hide-scrollbars",
  "--disable-dev-shm-usage",
  "--force-color-profile=srgb",
  // Subpixel antialiasing tints glyph edges red/blue, which reads as fringing
  // once the PNG lands on a background other than the one it was rendered on.
  "--disable-lcd-text",
  "--disable-background-timer-throttling",
  "--mute-audio",
];

export class Engine {
  constructor() {
    /** @type {Map<string, any>} browsers, one per distinct network policy */
    this.browsers = new Map();
    this.browser = null;
    this.playwright = null;
    /** @type {Map<string, any>} */
    this.contexts = new Map();
    /** @type {Map<string, any>} */
    this.staticPages = new Map();
    /** @type {Map<string, {page:any, context:any, meta:Record<string,any>}>} */
    this.sessions = new Map();
    this.launching = new Map();
    this.channel = null;
  }

  /**
   * The browser enforcing `policy`. The default policy's browser is the one
   * `shot warm` opens; a second is launched only if some shot asks for a
   * different network policy, since the policy is a launch flag.
   */
  async start(policy) {
    const key = policyKey(policy);
    const existing = this.browsers.get(key);
    if (existing) return existing;
    if (this.launching.has(key)) return this.launching.get(key);

    const pending = (async () => {
      const pw = this.playwright ?? (this.playwright = await loadPlaywright());
      const { browser, channel } = await launchChromium(pw, { args: [...LAUNCH_ARGS, ...policyArgs(policy)] });
      this.browsers.set(key, browser);
      this.channel = channel;
      if (key === "open") this.browser = browser;
      return browser;
    })();
    this.launching.set(key, pending);
    return pending;
  }

  contextOptions({ width, height, scale, theme, reducedMotion = true }) {
    return {
      viewport: { width, height },
      deviceScaleFactor: scale,
      colorScheme: theme,
      reducedMotion: reducedMotion ? "reduce" : "no-preference",
      // A stable frame: the same shot on macOS and in CI should differ only in
      // font rasterization, not in locale-formatted dates or timezone.
      locale: "en-US",
      timezoneId: "UTC",
    };
  }

  /** A pooled context. Shared between one-shot captures; sessions get their own. */
  async context(frame, policy) {
    const browser = await this.start(policy);
    const key = `${policyKey(policy)}:${frame.width}x${frame.height}@${frame.scale}:${frame.theme}:${frame.reducedMotion !== false}`;
    let ctx = this.contexts.get(key);
    if (ctx) return ctx;
    ctx = await browser.newContext(this.contextOptions(frame));
    this.contexts.set(key, ctx);
    return ctx;
  }

  /**
   * Render a self-contained HTML document and shoot one element from it.
   * @param {{html:string, selector?:string, theme?:string, scale?:number,
   *          format?:string, quality?:number, transparent?:boolean,
   *          width?:number, height?:number}} opts
   */
  async captureStatic(opts) {
    const theme = opts.theme ?? "dark";
    const scale = opts.scale ?? 2;
    // Generous enough that a card is rarely larger than the frame; Playwright
    // still stitches if it is, this just avoids the slow path.
    const width = opts.width ?? 2200;
    const height = opts.height ?? 1600;
    const key = `${width}x${height}@${scale}:${theme}:static`;

    let page = this.staticPages.get(key);
    if (!page || page.isClosed()) {
      const ctx = await this.context({ width, height, scale, theme });
      page = await ctx.newPage();
      this.staticPages.set(key, page);
    }

    await page.setContent(opts.html, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);
    return page.locator(opts.selector ?? "#canvas").first().screenshot({
      type: opts.format === "jpeg" ? "jpeg" : "png",
      ...(opts.format === "jpeg" ? { quality: opts.quality ?? 92 } : {}),
      omitBackground: Boolean(opts.transparent),
      animations: "disabled",
      scale: "device",
    });
  }

  /** Navigate, drive, and shoot — the one-shot page path. */
  async capturePage(opts) {
    const frame = frameOf(opts);
    const ctx = await this.context(frame, policyOf(opts));
    if (opts.storage) await seedStorage(ctx, opts.storage);
    const page = await ctx.newPage();
    try {
      await page.goto(opts.url, { waitUntil: opts.waitUntil ?? "domcontentloaded", timeout: opts.timeout ?? 30_000 });
      const trace = await preparePage(page, opts);
      const buf = await shootPage(page, opts);
      return { buf, trace };
    } finally {
      await page.close();
    }
  }

  /**
   * Open a page and keep it. The returned handle is addressed by name on later
   * requests, so an agent can click, look, click again, and look again without
   * paying for a reload — and without the daemon having to guess which of
   * several open flows a request belongs to.
   */
  async openSession(name, opts) {
    await this.closeSession(name);
    const frame = frameOf(opts);
    const browser = await this.start(policyOf(opts));
    const context = await browser.newContext(this.contextOptions(frame));
    if (opts.storage) await seedStorage(context, opts.storage);
    const page = await context.newPage();
    await page.goto(opts.url, { waitUntil: opts.waitUntil ?? "domcontentloaded", timeout: opts.timeout ?? 30_000 });
    const trace = await preparePage(page, opts);
    const meta = {
      name,
      url: page.url(),
      frame,
      openedAt: Date.now(),
      actions: trace.length,
    };
    this.sessions.set(name, { page, context, meta });
    return meta;
  }

  session(name) {
    const s = this.sessions.get(name);
    if (!s || s.page.isClosed()) {
      throw new Error(`no open session "${name}". Start one with: shot open <route> --session ${name}`);
    }
    return s;
  }

  /** Run actions against a held page, without shooting. */
  async actOnSession(name, opts) {
    const s = this.session(name);
    const trace = await runActions(s.page, opts.do ?? [], { baseUrl: opts.baseUrl, timeout: opts.timeout });
    s.meta.actions += trace.length;
    s.meta.url = s.page.url();
    return { trace, meta: s.meta };
  }

  /** Change a held page's frame in place — the responsive path for a session. */
  async resizeSession(name, frame) {
    const s = this.session(name);
    await s.page.setViewportSize({ width: frame.width, height: frame.height });
    // deviceScaleFactor is fixed at context creation, so a scale change is the
    // one resize that genuinely needs the page rebuilt; reload keeps the URL.
    s.meta.frame = { ...s.meta.frame, width: frame.width, height: frame.height };
    return s.meta;
  }

  async shootSession(name, opts) {
    const s = this.session(name);
    const trace = opts.do?.length
      ? await runActions(s.page, opts.do, { baseUrl: opts.baseUrl, timeout: opts.timeout })
      : [];
    if (opts.hide || opts.css || opts.settle) await preparePage(s.page, { ...opts, do: [] });
    const buf = await shootPage(s.page, opts);
    s.meta.actions += trace.length;
    s.meta.url = s.page.url();
    return { buf, trace, meta: s.meta };
  }

  async closeSession(name) {
    const s = this.sessions.get(name);
    if (!s) return false;
    this.sessions.delete(name);
    await s.context.close().catch(() => {});
    return true;
  }

  listSessions() {
    return [...this.sessions.values()].map((s) => ({ ...s.meta, closed: s.page.isClosed() }));
  }

  async close() {
    for (const name of [...this.sessions.keys()]) await this.closeSession(name);
    for (const ctx of this.contexts.values()) await ctx.close().catch(() => {});
    this.contexts.clear();
    this.staticPages.clear();
    for (const browser of this.browsers.values()) await browser.close().catch(() => {});
    this.browsers.clear();
    this.browser = null;
    this.launching.clear();
  }
}

/** @param {Record<string, any>} opts */
export function policyOf(opts) {
  return { offline: Boolean(opts.offline), block: opts.block ?? [] };
}

/** @param {Record<string, any>} opts */
export function frameOf(opts) {
  return {
    width: opts.width ?? 1440,
    height: opts.height ?? 900,
    scale: opts.scale ?? 2,
    theme: opts.theme ?? "dark",
    reducedMotion: opts.reducedMotion !== false,
  };
}

async function seedStorage(context, storage) {
  await context.addInitScript((entries) => {
    for (const [k, v] of entries) {
      try {
        window.localStorage.setItem(k, v);
      } catch {
        /* storage may be blocked; the shot is still worth taking */
      }
    }
  }, Object.entries(storage));
}

/** Waits, ordered actions, and the cosmetic fixes every shot wants. */
async function preparePage(page, opts) {
  const timeout = opts.timeout ?? 30_000;
  if (opts.waitFor) await page.waitForSelector(opts.waitFor, { state: "visible", timeout });
  if (opts.waitForText) {
    await page.waitForFunction((t) => document.body.innerText.includes(t), opts.waitForText, { timeout });
  }
  if (opts.settle && opts.settle !== "none") await settle(page, opts.settle);

  const trace = await runActions(page, opts.do ?? [], { baseUrl: opts.baseUrl, timeout: opts.actionTimeout });
  if (trace.length && opts.settle && opts.settle !== "none") await settle(page, "fast");

  // Dev-mode chrome is not product UI, and dev mode is the only way to run the
  // mock server the app shots come from.
  const hide = ["nextjs-portal", ...(opts.hide ?? [])];
  await page.addStyleTag({ content: `${hide.join(",")} { display:none !important }` });
  if (opts.css) await page.addStyleTag({ content: opts.css });
  if (opts.delay) await page.waitForTimeout(opts.delay);
  await page.evaluate(() => document.fonts.ready);
  return trace;
}

async function shootPage(page, opts) {
  const shotOpts = {
    type: opts.format === "jpeg" ? "jpeg" : "png",
    ...(opts.format === "jpeg" ? { quality: opts.quality ?? 92 } : {}),
    animations: "disabled",
    caret: "hide",
    ...(opts.mask?.length ? { mask: opts.mask.map((m) => page.locator(m)) } : {}),
    ...(opts.transparent ? { omitBackground: true } : {}),
  };
  if (opts.element) return page.locator(opts.element).first().screenshot(shotOpts);
  return page.screenshot({ ...shotOpts, fullPage: Boolean(opts.fullPage) });
}

/**
 * Wait for a *populated* frame, not merely a mounted one.
 *
 * The shell renders before its fetches resolve, so gating on the ready hook
 * alone reliably captures loading skeletons and a "Reconnecting…" badge. Every
 * placeholder in the app is the same `.animate-pulse` Skeleton, which makes
 * their absence a dependable "content is in" signal, and the status bar carries
 * a `data-connection` hook for the stream.
 *
 * The connection wait is not an extra: a shot taken a moment early shows the
 * room mid-"Reconnecting…", which reads as a broken app in a published image.
 * It costs a second or two when the stream is coming up and nothing at all on a
 * page that has no indicator, so both levels wait — `full` just waits longer.
 *
 * Each step is best-effort: this also runs against a real backend, where a rail
 * may legitimately stay empty, and an empty rail is not a reason to fail a shot.
 */
const SETTLE_BUDGET = {
  fast: { shell: 15_000, skeleton: 4_000, connection: 6_000 },
  full: { shell: 15_000, skeleton: 15_000, connection: 12_000 },
};

async function settle(page, level) {
  const soft = (p) => p.catch(() => {});
  const budget = SETTLE_BUDGET[level] ?? SETTLE_BUDGET.fast;

  await soft(page.waitForSelector('[data-app-shell="ready"]', { state: "visible", timeout: budget.shell }));
  await soft(
    page.waitForFunction(() => document.querySelectorAll(".animate-pulse").length === 0, null, {
      timeout: budget.skeleton,
    }),
  );
  await soft(
    page.waitForFunction(
      () => {
        const badge = document.querySelector("[data-connection]");
        // No indicator on this route means there is no stream to wait for; the
        // text check is the fallback for a page that predates the hook.
        if (!badge) return !document.body.innerText.includes("Reconnecting");
        return badge.getAttribute("data-connection") === "live";
      },
      null,
      { timeout: budget.connection },
    ),
  );
  await soft(page.evaluate(() => document.fonts.ready));
}

/** Write a capture to disk, creating parents. */
export async function writeShot(path, buf) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, buf);
  return { path, bytes: buf.length, ...pngSize(buf) };
}
