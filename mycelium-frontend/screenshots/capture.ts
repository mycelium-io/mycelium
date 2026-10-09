// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The app's camera. Drives each entry in the shot manifest against the frontend
 * running in mock mode (`pnpm dev:mock`, so every state renders with no
 * backend/SLIM/LLM), optimizes the PNGs, and writes committed assets into docs/
 * and the splash repo per `targets.ts`.
 *
 * Conceptually a sibling of docs/generate_docs.py: both regenerate published
 * artifacts from a source of truth. This one's source of truth is the real UI.
 *
 *   pnpm screenshots            # boot mock, capture all shots, publish
 *   pnpm screenshots --keep     # attach to an already-running dev:mock on $PORT
 *   pnpm screenshots room-board  # capture a subset by shot id
 *   pnpm screenshots --offline  # don't wait on webfont CDNs
 *
 * The browser work belongs to `shotkit/`, the repo's screenshot utility: booting
 * the mock server, finding a usable Chromium, waiting for a populated frame and
 * driving the page are the same problems whether the caller is this pipeline or
 * an agent at a terminal, and they were solved twice before. What stays here is
 * what is genuinely publication's business — which shots exist, how they are
 * optimized, and where the files land.
 */

import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import sharp from "sharp";
// shotkit is plain ESM JavaScript; `allowJs` means its JSDoc types are checked
// here, so a signature change over there fails this typecheck rather than this
// pipeline at runtime.
import { capture, shutdown } from "../../shotkit/src/api.mjs";
import { ensureMockServer, stopMockServer } from "../../shotkit/src/app.mjs";
import { SHOTS, VIEWPORTS, type Shot } from "./shots.ts";
import { TARGETS } from "./targets.ts";

function log(msg: string): void {
  process.stdout.write(`[screenshots] ${msg}\n`);
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

/** One manifest entry -> one shotkit spec. */
function specFor(shot: Shot, baseUrl: string, offline: boolean) {
  const vp = VIEWPORTS[shot.viewport];
  return {
    op: "app",
    baseUrl,
    route: shot.route,
    theme: shot.theme,
    width: vp.width,
    height: vp.height,
    scale: vp.scale,
    // Deterministic fixtures mean the wait can gate on content rather than a
    // timeout; `full` also holds for the SSE badge to read "Live".
    settle: "full",
    waitFor: shot.waitFor,
    element: shot.clip,
    // Reach a view/rail behind a tab (Negotiate, Network, Memory) before
    // shooting, then any state only actions can reach (a dialog filled in).
    do: [...(shot.steps ?? []).flatMap((name) => [`click:${name}`, "sleep:600"]), ...(shot.actions ?? [])],
    // The capture boots a cold dev server: a view's first open compiles it and
    // its routes on demand, so a wait for its data (the board's pull request
    // states) can outlast shotkit's 15s default on a runner.
    actionTimeout: 45_000,
    // next-themes reads the theme from localStorage before first paint; seed it
    // so there's no flash of the default theme in the capture. The shots are
    // taken as Morgan (@operator), the mock rooms' person, so a fresh browser
    // doesn't open on "What should we call you?" over the page.
    // Shots share a browser's storage, so each says everything it depends on: a
    // fresh one clears who's looking, and a shot that types into a room's
    // message box would leave a draft behind (drafts are kept per room), so
    // every shot starts those rooms empty.
    storage: {
      theme: shot.theme,
      ...(shot.fresh
        ? { "mycelium.principal": "", "mycelium.name-asked": "" }
        : { "mycelium.principal": "operator", "mycelium.name-asked": "1" }),
      ...Object.fromEntries(["checkout", "scratch", "storefront"].map((room) => [`mycelium.draft:${room}`, ""])),
      // A room remembers its open tabs and the rail its split, so a shot that
      // opened the Board or folded a section would hand that to the next one.
      // Empty reads as "nothing saved": every shot starts on the defaults.
      ...Object.fromEntries(["checkout", "scratch", "storefront"].map((room) => [`mycelium.dock.${room}`, ""])),
      // The panels library keys a layout by its group id and its panel ids.
      ...Object.fromEntries(
        ["mycelium:shell:rooms:workspace", "mycelium:room:main:inspector", "mycelium:rail:agents:memory"].map(
          (layout) => [`react-resizable-panels:${layout}`, ""],
        ),
      ),
    },
    offline,
    stdout: true,
  };
}

async function main(): Promise<void> {
  const argv = process.argv.slice(2);
  const keep = argv.includes("--keep");
  const offline = argv.includes("--offline");
  const ids = argv.filter((a) => !a.startsWith("--"));
  const shots = ids.length ? SHOTS.filter((s) => ids.includes(s.id)) : SHOTS;
  if (shots.length === 0) {
    throw new Error(`no shots matched ${JSON.stringify(ids)}`);
  }

  const baseUrl = keep
    ? `http://localhost:${process.env.PORT ?? 3000}`
    : await ensureMockServer({ log });
  log(`capturing against ${baseUrl}`);

  try {
    for (const shot of shots) {
      const result = await capture(specFor(shot, baseUrl, offline), { log });
      const written = await publish(shot, Buffer.from(result.base64, "base64"));
      if (written.length === 0) {
        log(`captured ${shot.id} in ${result.ms.total}ms (no target configured — not published)`);
      } else {
        log(`captured ${shot.id} in ${result.ms.total}ms -> ${written.length} file(s)`);
      }
    }
  } finally {
    await shutdown();
    if (!keep) stopMockServer();
  }
  log(`done — ${shots.length} shot(s)`);
}

main().catch((err) => {
  process.stderr.write(`[screenshots] failed: ${err?.stack ?? err}\n`);
  process.exit(1);
});
