// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The app's camera. Boots the frontend in mock mode (`pnpm dev:mock`, so every
 * state renders with no backend/SLIM/LLM), drives each entry in the shot
 * manifest with Playwright, optimizes the PNGs, and writes committed assets into
 * docs/ and the splash repo per `targets.ts`.
 *
 * Conceptually a sibling of docs/generate_docs.py: both regenerate published
 * artifacts from a source of truth. This one's source of truth is the real UI.
 *
 *   pnpm screenshots            # boot mock, capture all shots, publish
 *   pnpm screenshots --keep     # attach to an already-running dev:mock on $PORT
 *   pnpm screenshots room-plan  # capture a subset by shot id
 */

import { spawn, type ChildProcess } from "node:child_process";
import { createServer } from "node:net";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium, type Browser } from "playwright";
import sharp from "sharp";
import { SHOTS, VIEWPORTS, type Shot } from "./shots.ts";
import { TARGETS } from "./targets.ts";

const READY_SELECTOR = '[data-app-shell="ready"]';

function log(msg: string): void {
  process.stdout.write(`[screenshots] ${msg}\n`);
}

async function freePort(): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const srv = createServer();
    srv.on("error", reject);
    srv.listen(0, () => {
      const addr = srv.address();
      const port = typeof addr === "object" && addr ? addr.port : 0;
      srv.close(() => resolvePort(port));
    });
  });
}

async function waitForServer(url: string, timeoutMs = 60_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { redirect: "manual" });
      if (res.status > 0) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`dev:mock did not become ready at ${url} within ${timeoutMs}ms`);
}

async function bootMockServer(port: number): Promise<ChildProcess> {
  log(`booting dev:mock on :${port}`);
  const child = spawn("pnpm", ["dev:mock", "--port", String(port)], {
    env: { ...process.env, MYCELIUM_UI_MOCK: "1", PORT: String(port) },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout?.on("data", (d) => process.env.DEBUG_SCREENSHOTS && process.stdout.write(d));
  child.stderr?.on("data", (d) => process.env.DEBUG_SCREENSHOTS && process.stderr.write(d));
  // Address the dev server as `localhost`, not `127.0.0.1`: Next 16's dev-server
  // cross-origin protection on `/_next/*` only allow-lists `localhost` by
  // default, so a browser (which sends Sec-Fetch/Origin headers) 403s on every
  // JS chunk over 127.0.0.1 and the app never hydrates.
  await waitForServer(`http://localhost:${port}/`);
  log("dev:mock ready");
  return child;
}

/** Raw PNG buffer -> optimized 1x + optional @2x, written to every target. */
async function publish(shot: Shot, raw: Buffer): Promise<string[]> {
  const targets = TARGETS[shot.id] ?? [];
  const scale = VIEWPORTS[shot.viewport].scale;
  const written: string[] = [];

  // The raw capture is at deviceScaleFactor pixel density: that IS the @2x asset.
  const oneX = await sharp(raw)
    .resize({ width: Math.round(VIEWPORTS[shot.viewport].width) })
    .png({ compressionLevel: 9, palette: true })
    .toBuffer();
  const twoX = await sharp(raw).png({ compressionLevel: 9, palette: true }).toBuffer();

  for (const t of targets) {
    await mkdir(t.dir, { recursive: true });
    const base = join(t.dir, `${t.name}.png`);
    await writeFile(base, oneX);
    written.push(base);
    if (t.retina && scale > 1) {
      const hi = join(t.dir, `${t.name}@2x.png`);
      await writeFile(hi, twoX);
      written.push(hi);
    }
  }
  return written;
}

/**
 * Wait for the app to reach a stable, populated frame: the shell mounts before
 * its fetches/SSE resolve, so shooting on `ready` alone catches loading
 * skeletons and a "Reconnecting…" badge. Every loading placeholder is the one
 * `.animate-pulse` Skeleton, so their absence is a reliable "content in" signal.
 */
async function settle(page: import("playwright").Page): Promise<void> {
  // Rooms list resolved (sidebar populated, not the "No rooms yet" empty state).
  await page.waitForSelector('a[href^="/room/"]', { state: "visible", timeout: 15_000 });
  // All Skeletons detached — channel + members + rails have their data.
  await page.waitForFunction(() => document.querySelectorAll(".animate-pulse").length === 0, null, {
    timeout: 15_000,
  });
  // SSE connected ("Live", not "Reconnecting…"). Best-effort: some routes never
  // open a stream, so don't fail the shot if it stays disconnected.
  await page
    .waitForFunction(() => document.body.innerText.includes("Live"), null, { timeout: 8_000 })
    .catch(() => {});
  // Fonts loaded (Cormorant Garamond / IBM Plex Sans) so no reflow mid-shot.
  await page.evaluate(() => document.fonts.ready);
}

async function captureShot(browser: Browser, baseUrl: string, shot: Shot): Promise<void> {
  const vp = VIEWPORTS[shot.viewport];
  const context = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    deviceScaleFactor: vp.scale,
    colorScheme: shot.theme,
  });
  // next-themes reads the theme from localStorage before first paint; seed it so
  // there's no flash of the default theme in the capture.
  await context.addInitScript((theme) => {
    window.localStorage.setItem("theme", theme);
  }, shot.theme);

  const page = await context.newPage();
  try {
    // The room opens an SSE stream, so the network never goes idle — gate on the
    // shell hook mounting instead.
    await page.goto(`${baseUrl}${shot.route}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(shot.waitFor ?? READY_SELECTOR, { state: "visible" });
    await settle(page);
    // Reach a view/rail behind a tab (Negotiate, Network, Memory) before shooting.
    for (const name of shot.steps ?? []) {
      await page.getByRole("button", { name, exact: true }).first().click();
      await page.waitForTimeout(600);
    }
    // Hide the Next.js dev-tools indicator (the "N" / "Issues" badge) — it's dev
    // chrome, not product UI, and dev mode is the only way to run the mock.
    await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });

    const clip = shot.clip ? await page.locator(shot.clip).first() : null;
    const raw = clip
      ? await clip.screenshot({ type: "png" })
      : await page.screenshot({ type: "png" });

    const written = await publish(shot, raw);
    if (written.length === 0) {
      log(`captured ${shot.id} (no target configured — not published)`);
    } else {
      log(`captured ${shot.id} -> ${written.length} file(s)`);
    }
  } finally {
    await context.close();
  }
}

async function main(): Promise<void> {
  const argv = process.argv.slice(2);
  const keep = argv.includes("--keep");
  const ids = argv.filter((a) => !a.startsWith("--"));
  const shots = ids.length ? SHOTS.filter((s) => ids.includes(s.id)) : SHOTS;
  if (shots.length === 0) {
    throw new Error(`no shots matched ${JSON.stringify(ids)}`);
  }

  let server: ChildProcess | null = null;
  const port = keep ? Number(process.env.PORT ?? 3000) : await freePort();
  if (keep) {
    log(`attaching to existing dev:mock on :${port}`);
    await waitForServer(`http://localhost:${port}/`);
  } else {
    server = await bootMockServer(port);
  }
  const baseUrl = `http://localhost:${port}`;

  const browser = await chromium.launch();
  try {
    for (const shot of shots) {
      await captureShot(browser, baseUrl, shot);
    }
  } finally {
    await browser.close();
    if (server) {
      server.kill("SIGTERM");
    }
  }
  log(`done — ${shots.length} shot(s)`);
}

main().catch((err) => {
  process.stderr.write(`[screenshots] failed: ${err?.stack ?? err}\n`);
  process.exit(1);
});
