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

import { spawn } from "node:child_process";
import { closeSync, openSync, readFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { capture, shutdown } from "../shotkit/src/api.mjs";
import { soundTake } from "./audio/build.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../mycelium-frontend");
const argv = process.argv.slice(2);
const quick = argv.includes("--quick");
const sound = !quick && !argv.includes("--no-sound");
const outAt = argv.indexOf("--out");
const out = resolve(outAt >= 0 ? argv[outAt + 1] : join(here, quick ? "../.shotkit/demo-quick.mp4" : "mycelium-demo.mp4"));

const flow = JSON.parse(readFileSync(join(here, "demo.json"), "utf8"));
delete flow.$comment;

/** A port nothing is listening on. */
const freePort = () =>
  new Promise((res, rej) => {
    const srv = createServer();
    srv.on("error", rej);
    srv.listen(0, () => {
      const { port } = /** @type {import("node:net").AddressInfo} */ (srv.address());
      srv.close(() => res(port));
    });
  });

async function waitFor(url, ms) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`${url} did not come up in ${ms / 1000}s`);
}

// Next allows one dev server per folder, and a take needs one of its own.
try {
  const { pid, appUrl } = JSON.parse(readFileSync(join(frontend, ".next/dev/lock"), "utf8"));
  process.kill(pid, 0);
  console.error(`A dev server is already running in mycelium-frontend (${appUrl}, pid ${pid}). Stop it first:`);
  console.error(`  kill ${pid}`);
  process.exit(1);
} catch {
  /* no lock, or its process is gone */
}

const port = await freePort();
const logPath = join(tmpdir(), `mycelium-demo-${port}.log`);
const logFd = openSync(logPath, "w");
const server = spawn("npx", ["next", "dev", "--port", String(port)], {
  cwd: frontend,
  env: { ...process.env, MYCELIUM_UI_MOCK: "1", MYCELIUM_UI_MOCK_SCENARIO: "demo" },
  stdio: ["ignore", logFd, logFd],
  detached: true,
});
closeSync(logFd);
const stop = () => {
  try {
    process.kill(-server.pid, "SIGTERM");
  } catch {
    /* already gone */
  }
};
process.on("exit", stop);

try {
  // Next serves `localhost` only (its dev-server origin guard), so the take does too.
  const baseUrl = `http://localhost:${port}`;
  console.error(`demo server on ${baseUrl} (log: ${logPath})`);
  await waitFor(`${baseUrl}/api/rooms`, 180_000);
  // Compile the room page once, so the take doesn't open on a compile.
  await fetch(`${baseUrl}${flow.route}`).catch(() => {});

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
  stop();
}
