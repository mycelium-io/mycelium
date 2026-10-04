#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Record the product demo: the real app, driven through the flow in
 * `demo.json`, over the frontend's demo scenario, with its sound.
 *
 *   node mycelium-promo/record.mjs              # the staged take with sound → mycelium-promo/mycelium-demo.mp4
 *   node mycelium-promo/record.mjs --quick      # the flow alone, flat, silent and fast, to check it
 *   node mycelium-promo/record.mjs --no-sound   # the staged take, silent
 *   node mycelium-promo/record.mjs --out x.mp4
 *
 * The sound is the drone (audio/score.mjs) under the take's clicks and keys,
 * mixed and muxed by shotkit (audio/build.mjs re-mixes a take on its own).
 *
 * Each run boots its own `next dev` with `MYCELIUM_UI_MOCK_SCENARIO=demo`, since
 * the scenario's acts play once per server: a second take against the same
 * server would find the story already told.
 */

import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { capture, shutdown } from "../shotkit/src/api.mjs";
import { soundTake } from "./audio/build.mjs";
import { refuseIfRunning, startScenario } from "./server.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const quick = argv.includes("--quick");
const sound = !quick && !argv.includes("--no-sound");
const outAt = argv.indexOf("--out");
const out = resolve(outAt >= 0 ? argv[outAt + 1] : join(here, quick ? "../.shotkit/demo-quick.mp4" : "mycelium-demo.mp4"));

const flow = JSON.parse(readFileSync(join(here, "demo.json"), "utf8"));
delete flow.$comment;

refuseIfRunning();
mkdirSync(dirname(out), { recursive: true });
const { baseUrl, stop } = await startScenario("demo", [flow.route]);

try {
  const spec = quick
    ? { ...flow, demo: false, tilt: undefined, backdrop: undefined, intro: undefined, outro: undefined }
    : flow;
  const result = await capture(
    { op: "video", ...spec, baseUrl, out },
    { log: (m) => console.error(`[shot] ${m}`) },
  );
  console.error(`${result.frames} frames, ${Math.round(result.durationMs / 100) / 10}s, ${result.width}x${result.height}`);
  if (sound) await soundTake(result.path, { log: (m) => console.error(`[sound] ${m}`) });
  console.log(result.path);
} finally {
  await shutdown();
  await stop();
}
