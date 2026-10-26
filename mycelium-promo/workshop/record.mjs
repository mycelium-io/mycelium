#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Record the workshop's multiplayer videos: a replay of a real run in the
 * `release-planning` room, driven through `takes/<take>.json` over the
 * frontend's workshop scenario (`MYCELIUM_UI_MOCK_SCENARIO=workshop:<take>`,
 * `src/mocks/workshop.ts`).
 *
 *   node mycelium-promo/workshop/record.mjs                       # every take → ../slides/workshop/media/
 *   node mycelium-promo/workshop/record.mjs accord --out ~/tmp     # one take, somewhere else
 *   node mycelium-promo/workshop/record.mjs --raw concord          # keep the take as recorded
 *
 * Each take is the app seen as Julia, at 1920x1080, silent and without
 * captions (the talk is spoken over it). It's encoded for the web and gets a
 * poster frame at `poster` seconds.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { capture, shutdown } from "../../shotkit/src/api.mjs";
import { refuseIfRunning, startScenario } from "../server.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const SCRATCH = join(repo, ".shotkit/workshop");

/** What every take shares: Julia's browser, the room, the camera. Each
 *  person's laptop is listed as one of hers, so the Members rail names the
 *  machine each agent runs on (it names only your own). */
const DEFAULTS = {
  route: "/room/release-planning",
  viewport: "1920x1080@1",
  theme: "dark",
  format: "mp4",
  fps: 30,
  maxSeconds: 150,
  actionTimeout: 90000,
  moveMs: 650,
  dwell: 450,
  leadIn: 700,
  tail: 1600,
  storage: {
    "mycelium.principal": "julia",
    "mycelium.name-asked": "1",
    "mycelium.machines": JSON.stringify(["julias-mbp", "jodees-mbp", "marcs-mbp"]),
  },
};

const argv = process.argv.slice(2);
const raw = argv.includes("--raw");
const outAt = argv.indexOf("--out");
const OUT = resolve(outAt >= 0 ? argv[outAt + 1] : join(repo, "../../slides/workshop/media"));
const all = readdirSync(join(here, "takes"))
  .filter((f) => f.endsWith(".json"))
  .map((f) => f.slice(0, -5));
const named = argv.filter((a, i) => !a.startsWith("--") && argv[i - 1] !== "--out");
const takes = named.length ? named : all;
for (const t of takes) {
  if (!all.includes(t)) {
    console.error(`no take ${t}; there are: ${all.join(", ")}`);
    process.exit(2);
  }
}

refuseIfRunning();
mkdirSync(OUT, { recursive: true });
mkdirSync(SCRATCH, { recursive: true });

const ffmpeg = (...args) => execFileSync("ffmpeg", ["-loglevel", "error", "-y", ...args], { stdio: "inherit" });
const mb = (path) => (statSync(path).size / 1e6).toFixed(1);

for (const take of takes) {
  const spec = JSON.parse(readFileSync(join(here, "takes", `${take}.json`), "utf8"));
  const { $comment, poster = 3, ...flow } = spec;
  const shot = { ...DEFAULTS, ...flow, storage: { ...DEFAULTS.storage, ...(flow.storage ?? {}) } };
  const { baseUrl, stop } = await startScenario(`workshop:${take}`, [shot.route]);
  try {
    const recorded = join(SCRATCH, `${take}.mp4`);
    const result = await capture(
      { op: "video", ...shot, baseUrl, out: recorded },
      { log: (m) => console.error(`[${take}] ${m}`) },
    );
    const seconds = Math.round(result.durationMs / 100) / 10;
    console.error(`[${take}] ${result.frames} frames, ${seconds}s, ${result.width}x${result.height}`);
    if (raw) {
      console.log(result.path);
      continue;
    }
    const video = join(OUT, `${take}.mp4`);
    const tmp = join(SCRATCH, `${take}.web.mp4`);
    ffmpeg(
      "-i", result.path,
      "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "24",
      "-pix_fmt", "yuv420p", "-movflags", "+faststart",
      tmp,
    );
    renameSync(tmp, video);
    ffmpeg("-ss", String(poster), "-i", result.path, "-frames:v", "1", "-q:v", "3", join(OUT, `${take}.jpg`));
    rmSync(`${result.path}.sounds.json`, { force: true });
    console.log(`${video} (${mb(video)} MB, ${seconds}s)`);
  } finally {
    await stop();
  }
}
await shutdown();
