// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Boot the frontend in a mock scenario for one take, and stop it after.
 *
 * Shared by the product demo (`record.mjs`) and the Learn videos
 * (`learn/record.mjs`). Each take gets a `next dev` of its own, since a
 * scenario's acts play once per server: a second take against the same server
 * would find the story already told.
 */

import { spawn } from "node:child_process";
import { closeSync, openSync, readFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const FRONTEND = resolve(here, "../mycelium-frontend");

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

/** Exit if a dev server already holds the frontend: Next allows one per folder. */
export function refuseIfRunning() {
  try {
    const { pid, appUrl } = JSON.parse(readFileSync(join(FRONTEND, ".next/dev/lock"), "utf8"));
    process.kill(pid, 0);
    console.error(`A dev server is already running in mycelium-frontend (${appUrl}, pid ${pid}). Stop it first:`);
    console.error(`  kill ${pid}`);
    process.exit(1);
  } catch {
    /* no lock, or its process is gone */
  }
}

/**
 * Start `next dev` with the mock in `scenario`, wait until it answers, and warm
 * `routes` so the take doesn't open on a compile.
 * @param {string} scenario
 * @param {string[]} routes
 * @returns {Promise<{baseUrl: string, stop: () => Promise<void>}>}
 */
export async function startScenario(scenario, routes = []) {
  const port = await freePort();
  const logPath = join(tmpdir(), `mycelium-take-${port}.log`);
  const logFd = openSync(logPath, "w");
  const server = spawn("npx", ["next", "dev", "--port", String(port)], {
    cwd: FRONTEND,
    env: { ...process.env, MYCELIUM_UI_MOCK: "1", MYCELIUM_UI_MOCK_SCENARIO: scenario },
    stdio: ["ignore", logFd, logFd],
    detached: true,
  });
  closeSync(logFd);
  const exited = new Promise((r) => server.once("exit", r));
  const kill = () => {
    try {
      process.kill(-server.pid, "SIGTERM");
    } catch {
      /* already gone */
    }
  };
  process.once("exit", kill);
  // Next serves `localhost` only (its dev-server origin guard), so the take does too.
  const baseUrl = `http://localhost:${port}`;
  console.error(`${scenario} on ${baseUrl} (log: ${logPath})`);
  try {
    await waitFor(`${baseUrl}/api/rooms`, 180_000);
    for (const route of routes) await fetch(`${baseUrl}${route}`).catch(() => {});
  } catch (err) {
    kill();
    throw err;
  }
  return {
    baseUrl,
    stop: async () => {
      kill();
      await Promise.race([exited, new Promise((r) => setTimeout(r, 5000))]);
    },
  };
}
