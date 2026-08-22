// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * `shot doctor` and `shot bench`.
 *
 * The failures this tool can hit are all environmental — no browser downloaded,
 * no pty, no app listening — and each produces a different unhelpful error deep
 * in a capture. Doctor checks them up front and says which one is missing.
 */

import { existsSync } from "node:fs";
import { platform, release } from "node:os";
import { DEFAULT_OUT_DIR } from "./api.mjs";
import { FRONTEND_DIR } from "./app.mjs";
import { loadPlaywright, REPO_ROOT } from "./engine.mjs";
import { CANVAS_SOURCE } from "./mycelial.mjs";
import { candidates, launchChromium } from "./browser.mjs";
import { ptyAvailable } from "./run.mjs";
import { ping, socketPath } from "./ipc.mjs";

const ok = (m) => process.stdout.write(`  \x1b[32m✓\x1b[0m ${m}\n`);
const warn = (m) => process.stdout.write(`  \x1b[33m!\x1b[0m ${m}\n`);
const bad = (m) => process.stdout.write(`  \x1b[31m✗\x1b[0m ${m}\n`);
const head = (m) => process.stdout.write(`\n\x1b[1m${m}\x1b[0m\n`);

/** The host the frontend's own `<link>` points at, so the probe tests the real dependency. */
const FONT_PROBE_HOST = "fonts.googleapis.com";
const FONT_PROBE_URL = `https://${FONT_PROBE_HOST}/css2?family=IBM+Plex+Sans:wght@400`;
const FONT_PROBE_BUDGET_MS = 4000;

/**
 * Can this machine actually load a webfont?
 *
 * This is the failure that degrades a published screenshot silently. The
 * frontend links Google Fonts; where that host is unreachable the page still
 * renders — in fallback fonts, several seconds later — so nothing looks broken
 * except the image, and only to someone who knows what it should look like.
 * Nothing else doctor checks can be wrong without an obvious symptom, which is
 * why this one is worth a real network probe rather than an inference.
 */
async function probeWebfonts(pw) {
  if (!pw) {
    warn("skipped — no usable browser");
    return;
  }
  let browser;
  try {
    const launched = await launchChromium(pw, { args: [] });
    browser = launched.browser;
    const page = await (await browser.newContext()).newPage();
    // fetch() needs a real origin; about:blank is opaque and rejects outright.
    await page.goto("data:text/html,<title>probe</title>");
    const started = Date.now();
    // Bounded, because the answer is the same either way: a host that needs
    // longer than this is one every capture would be waiting on.
    const reachable = await page.evaluate(async ([url, budget]) => {
      try {
        const res = await fetch(url, { mode: "no-cors", signal: AbortSignal.timeout(budget) });
        return res.type === "opaque" || res.ok;
      } catch {
        return false;
      }
    }, [`${FONT_PROBE_URL}?_=shotkit`, FONT_PROBE_BUDGET_MS]);
    const ms = Date.now() - started;

    if (reachable) ok(`${FONT_PROBE_HOST} reachable in ${ms}ms — captures render with the real fonts`);
    else {
      warn(`${FONT_PROBE_HOST} unreachable (gave up after ${ms}ms)`);
      warn("  every app capture will wait on it, then fall back. Pass --offline to skip the wait.");
      warn("  published screenshots taken here will use fallback fonts — regenerate on a connected host.");
    }
  } catch (e) {
    warn(`probe failed: ${e.message.split("\n")[0]}`);
  } finally {
    await browser?.close().catch(() => {});
  }
}

export async function doctor() {
  head("host");
  ok(`node ${process.version} on ${platform()} ${release()}`);
  ok(`repo ${REPO_ROOT}`);
  ok(`output ${DEFAULT_OUT_DIR}`);

  head("browser");
  let pw = null;
  try {
    pw = await loadPlaywright();
    ok("playwright resolved");
  } catch (e) {
    bad(e.message);
  }
  if (pw) {
    try {
      const { browser, channel } = await launchChromium(pw, { args: [] });
      ok(`launches ${channel} (${browser.version()})`);
      await browser.close();
    } catch (e) {
      bad(e.message.split("\n")[0]);
    }
    const found = candidates();
    if (found.length) ok(`${found.length} browser binary(ies) on disk, best: ${found[0]}`);
    if (process.env.PLAYWRIGHT_BROWSERS_PATH) ok(`PLAYWRIGHT_BROWSERS_PATH=${process.env.PLAYWRIGHT_BROWSERS_PATH}`);
  }

  head("terminal capture");
  if (ptyAvailable) ok("script(1) present — commands run under a real pty, so Rich keeps its color");
  else warn("script(1) missing — falling back to FORCE_COLOR; box drawing and widths may differ");
  try {
    await import("highlight.js/lib/common");
    ok("highlight.js present — `shot code` highlights");
  } catch {
    warn("highlight.js missing — `shot code` renders plain. Run `npm install` in shotkit/");
  }

  head("backdrop");
  if (existsSync(`${REPO_ROOT}/${CANVAS_SOURCE}`)) ok(`${CANVAS_SOURCE} present — \`--backdrop mycelial\` grows the site's network`);
  else warn(`${CANVAS_SOURCE} missing — \`--backdrop mycelial\` errors; the other presets are unaffected`);

  head("webfonts");
  await probeWebfonts(pw);

  head("app");
  if (existsSync(`${FRONTEND_DIR}/node_modules`)) ok("mycelium-frontend deps installed — --mock can boot dev:mock");
  else warn("mycelium-frontend/node_modules missing — run `pnpm install` there before --mock");
  for (const port of [3000, 3001, 3002]) {
    try {
      const res = await fetch(`http://localhost:${port}/`, { redirect: "manual", signal: AbortSignal.timeout(600) });
      if (res.status > 0) ok(`app answering on :${port}`);
    } catch {
      /* nothing there, which is the normal case */
    }
  }

  head("daemon");
  const alive = await ping();
  if (alive) ok(`running · pid ${alive.pid} · ${alive.shots} shots · ${Math.round(alive.uptimeMs / 1000)}s up`);
  else warn(`not running (starts on first shot) · socket ${socketPath()}`);
  process.stdout.write("\n");
}

/**
 * Time the two paths that matter: one capture from nothing, then repeated
 * captures against a daemon that is already holding the browser.
 */
export async function bench(argv = []) {
  const n = Number(argv[0] ?? 5);
  const spec = { op: "term", argv: ["printf", "shotkit bench\\n"], name: "bench", backdrop: "ink" };

  const { capture, shutdown } = await import("./api.mjs");
  const t0 = Date.now();
  await capture(spec, { mode: "direct" });
  const cold = Date.now() - t0;
  await shutdown();

  const { ensureDaemon, send } = await import("./ipc.mjs");
  await ensureDaemon();
  await send("warm", {});

  const warm = [];
  for (let i = 0; i < n; i++) {
    const t = Date.now();
    await send("shot", { spec });
    warm.push(Date.now() - t);
  }
  warm.sort((a, b) => a - b);
  const median = warm[Math.floor(warm.length / 2)];

  process.stdout.write(
    `cold (no daemon, includes browser launch): ${cold}ms\n` +
      `warm x${n}: min ${warm[0]}ms · median ${median}ms · max ${warm[warm.length - 1]}ms\n` +
      `speedup: ${(cold / median).toFixed(1)}x\n`,
  );
}
