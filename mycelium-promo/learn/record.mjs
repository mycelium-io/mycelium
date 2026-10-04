#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Record the Learn videos: one take per course section, each the real app
 * driven through `takes/<take>.json` over the frontend's Learn scenario
 * (`MYCELIUM_UI_MOCK_SCENARIO=learn:<take>`, `src/mocks/learn.ts`).
 *
 *   node mycelium-promo/learn/record.mjs                  # every take → docs/learn/video/
 *   node mycelium-promo/learn/record.mjs pair-idea github # just these
 *   node mycelium-promo/learn/record.mjs --raw pair-idea  # keep the take as recorded, in .shotkit/learn/
 *
 * A take is encoded for the web after it is recorded (H.264, no sound, the
 * moov atom first so it starts playing at once) and gets a poster frame, at
 * `poster` seconds into the take. Its length goes into `index.json` beside the
 * videos, which generate_docs.py reads. The course that shows it names it as a
 * section's `video` in its course.json.
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { capture, shutdown } from "../../shotkit/src/api.mjs";
import { refuseIfRunning, startScenario } from "../server.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const OUT = join(repo, "docs/learn/video");
const SCRATCH = join(repo, ".shotkit/learn");

/** What every take shares: Sam's browser, the room, the camera. */
const DEFAULTS = {
  route: "/room/orders",
  viewport: "1440x900@1",
  theme: "dark",
  format: "mp4",
  fps: 30,
  maxSeconds: 150,
  actionTimeout: 45000,
  captionAt: "top",
  moveMs: 650,
  dwell: 450,
  leadIn: 700,
  tail: 1400,
  storage: { "mycelium.principal": "sam-rivera", "mycelium.name-asked": "1" },
};

const argv = process.argv.slice(2);
const raw = argv.includes("--raw");
const all = readdirSync(join(here, "takes"))
  .filter((f) => f.endsWith(".json"))
  .map((f) => f.slice(0, -5));
const named = argv.filter((a) => !a.startsWith("--"));
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

const INDEX = join(OUT, "index.json");
const index = existsSync(INDEX) ? JSON.parse(readFileSync(INDEX, "utf8")) : {};

const ffmpeg = (...args) => execFileSync("ffmpeg", ["-loglevel", "error", "-y", ...args], { stdio: "inherit" });
const mb = (path) => (statSync(path).size / 1e6).toFixed(1);

for (const take of takes) {
  const spec = JSON.parse(readFileSync(join(here, "takes", `${take}.json`), "utf8"));
  const { $comment, poster = 3, ...flow } = spec;
  const shot = { ...DEFAULTS, ...flow };
  const { baseUrl, stop } = await startScenario(`learn:${take}`, [shot.route]);
  try {
    const recorded = join(SCRATCH, `${take}.mp4`);
    const result = await capture(
      { op: "video", ...shot, baseUrl, out: recorded },
      { log: (m) => console.error(`[${take}] ${m}`) },
    );
    const seconds = Math.round(result.durationMs / 100) / 10;
    console.error(`[${take}] ${result.frames} frames, ${seconds}s, ${result.width}x${result.height}`);
    if (!raw) {
      const video = join(OUT, `${take}.mp4`);
      const tmp = join(SCRATCH, `${take}.web.mp4`);
      ffmpeg(
        "-i", result.path,
        "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "27", "-tune", "stillimage",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        tmp,
      );
      renameSync(tmp, video);
      ffmpeg("-ss", String(poster), "-i", result.path, "-frames:v", "1", "-q:v", "4", join(OUT, `${take}.jpg`));
      rmSync(`${result.path}.sounds.json`, { force: true });
      index[take] = { seconds };
      const sorted = Object.fromEntries(Object.entries(index).sort(([a], [b]) => a.localeCompare(b)));
      writeFileSync(INDEX, `${JSON.stringify(sorted, null, 2)}\n`);
      console.log(`${video} (${mb(video)} MB, ${seconds}s)`);
    } else {
      console.log(result.path);
    }
  } finally {
    await stop();
  }
}
await shutdown();
