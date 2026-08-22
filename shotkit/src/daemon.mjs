// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The warm half of shotkit: a background process holding the browser open.
 *
 * The point is entirely amortization. Chromium launch, context creation and
 * font loading cost roughly a second combined and are identical for every shot,
 * so they are paid once here and every later capture is a layout and a
 * rasterize. `--mock`'s Next dev server is held the same way and for the same
 * reason.
 *
 * It shuts itself down after an idle window (`SHOTKIT_IDLE_MS`, default 15
 * minutes) so an agent that takes one screenshot does not leave a browser
 * resident on the machine.
 */

import { createServer } from "node:net";
import { existsSync, unlinkSync } from "node:fs";
import { capture, engine, session, shutdown } from "./api.mjs";
import { ensureMockServer, mockStatus, stopMockServer } from "./app.mjs";
import { socketPath, sourceStamp } from "./ipc.mjs";

const IDLE_MS = Number(process.env.SHOTKIT_IDLE_MS ?? 15 * 60 * 1000);
/** Stamped once at boot; the client restarts this daemon when it moves. */
const STAMP = sourceStamp();
const startedAt = Date.now();
let shots = 0;
let idleTimer = null;
let stopping = false;

const path = socketPath();
if (existsSync(path)) {
  try {
    unlinkSync(path);
  } catch {
    /* fall through: listen() will report the real problem */
  }
}

function touchIdle() {
  if (idleTimer) clearTimeout(idleTimer);
  if (IDLE_MS <= 0) return;
  idleTimer = setTimeout(() => stop("idle"), IDLE_MS);
  idleTimer.unref?.();
}

/**
 * @param {string} reason
 * @param {boolean} [keepMock] leave the dev server running for the next daemon
 */
async function stop(reason, keepMock = false) {
  if (stopping) return;
  stopping = true;
  // A restart to pick up edited source should not cost a Next dev server that
  // took seconds to boot: it is spawned in its own process group, so leaving it
  // alone lets the replacement daemon adopt it from `.next/dev/lock`.
  if (!keepMock) stopMockServer();
  await shutdown().catch(() => {});
  server.close();
  try {
    unlinkSync(path);
  } catch {
    /* already gone */
  }
  process.exit(reason === "idle" ? 0 : 0);
}

const OPS = {
  async ping() {
    return { pid: process.pid, uptimeMs: Date.now() - startedAt, shots, socket: path, sourceStamp: STAMP };
  },
  async status() {
    const eng = engine();
    return {
      pid: process.pid,
      uptimeMs: Date.now() - startedAt,
      shots,
      idleMs: IDLE_MS,
      socket: path,
      sourceStamp: STAMP,
      browser: eng.browser ? { channel: eng.channel, contexts: eng.contexts.size } : null,
      mock: mockStatus(),
      sessions: eng.listSessions(),
    };
  },
  async warm(msg) {
    await engine().start();
    if (msg.mock) await ensureMockServer({ log: () => {} });
    return this.status();
  },
  async shot(msg) {
    shots += 1;
    return capture(msg.spec, { mode: "daemon", log: () => {} });
  },
  async session(msg) {
    if (msg.spec.op === "shoot") shots += 1;
    return session(msg.spec, { mode: "daemon", log: () => {} });
  },
  async stop(msg) {
    setTimeout(() => stop("requested", Boolean(msg.keepMock)), 10).unref?.();
    return { stopping: true, pid: process.pid };
  },
};

const server = createServer((sock) => {
  touchIdle();
  let buffer = "";
  sock.on("data", async (chunk) => {
    buffer += chunk;
    let nl;
    while ((nl = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, nl);
      buffer = buffer.slice(nl + 1);
      let reply;
      try {
        const msg = JSON.parse(line);
        const handler = OPS[msg.op];
        if (!handler) throw new Error(`unknown op: ${msg.op}`);
        reply = { ok: true, ...(await handler.call(OPS, msg)) };
      } catch (err) {
        reply = { ok: false, error: err?.stack ?? String(err) };
      }
      touchIdle();
      sock.write(`${JSON.stringify(reply)}\n`);
    }
  });
  sock.on("error", () => {});
});

server.listen(path, () => {
  touchIdle();
  // Warm the browser behind whatever request arrives first, so the client that
  // just started this daemon overlaps its own work with the launch.
  engine().start().catch(() => {});
  if (process.env.SHOTKIT_DAEMON_VERBOSE) process.stdout.write(`[shotkit] listening on ${path}\n`);
});

process.on("SIGTERM", () => stop("signal"));
process.on("SIGINT", () => stop("signal"));
