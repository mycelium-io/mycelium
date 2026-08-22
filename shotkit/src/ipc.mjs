// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Client side of the daemon: find the socket, start one if it isn't there, send
 * newline-delimited JSON.
 *
 * A Unix socket rather than a TCP port because it needs no port allocation, no
 * collision handling between two checkouts, and no listener reachable from off
 * the machine. The path is keyed by both the protocol version and the checkout,
 * so upgrading shotkit or working in a second clone starts a fresh daemon
 * instead of talking to a stale one.
 */

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { connect } from "node:net";
import { existsSync, readdirSync, statSync, unlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const PROTOCOL = 1;

/**
 * Newest mtime under `src/`. A daemon holds its modules in memory for its whole
 * life, so editing shotkit and taking a shot would otherwise silently run the
 * old code — the kind of bug that looks like the fix not working.
 */
export function sourceStamp() {
  let newest = 0;
  try {
    for (const f of readdirSync(HERE)) {
      if (f.endsWith(".mjs")) newest = Math.max(newest, statSync(join(HERE, f)).mtimeMs);
    }
  } catch {
    /* unreadable source: fall back to "unchanged" rather than restart-looping */
  }
  return Math.round(newest);
}

export function socketPath() {
  if (process.env.SHOTKIT_SOCKET) return process.env.SHOTKIT_SOCKET;
  const key = createHash("sha1").update(resolve(HERE, "..")).digest("hex").slice(0, 8);
  return join(tmpdir(), `shotkit-${PROTOCOL}-${key}.sock`);
}

/** One request, one response. Rejects if the socket is absent or dead. */
export function send(op, payload = {}, { timeout = 180_000 } = {}) {
  const path = socketPath();
  return new Promise((resolvePromise, reject) => {
    const sock = connect(path);
    let buffer = "";
    const timer = setTimeout(() => {
      sock.destroy();
      reject(new Error(`daemon timed out after ${timeout}ms`));
    }, timeout);

    sock.on("connect", () => sock.write(`${JSON.stringify({ op, ...payload })}\n`));
    sock.on("data", (chunk) => {
      buffer += chunk;
      const nl = buffer.indexOf("\n");
      if (nl === -1) return;
      clearTimeout(timer);
      sock.end();
      try {
        const msg = JSON.parse(buffer.slice(0, nl));
        if (msg.ok === false) reject(Object.assign(new Error(msg.error), { remote: true }));
        else resolvePromise(msg);
      } catch (err) {
        reject(err);
      }
    });
    sock.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

export async function ping({ timeout = 1500 } = {}) {
  try {
    return await send("ping", {}, { timeout });
  } catch {
    return null;
  }
}

/**
 * Return once a daemon is answering, starting one if needed.
 *
 * The daemon binds its socket before it launches Chromium, so this resolves in
 * a few hundred milliseconds and the browser warms up underneath the first
 * request rather than in front of it.
 */
export async function ensureDaemon({ idleMs, quiet = true } = {}) {
  const alive = await ping();
  if (alive && alive.sourceStamp === sourceStamp()) return alive;
  if (alive) {
    await send("stop", { keepMock: true }).catch(() => {});
    for (let i = 0; i < 60 && (await ping({ timeout: 200 })); i++) {
      await new Promise((r) => setTimeout(r, 50));
    }
  }

  const path = socketPath();
  // A socket file left behind by a killed daemon refuses connections forever.
  if (existsSync(path)) {
    try {
      unlinkSync(path);
    } catch {
      /* another process may have just cleaned it up */
    }
  }

  const child = spawn(process.execPath, [join(HERE, "daemon.mjs")], {
    detached: true,
    stdio: quiet ? "ignore" : "inherit",
    env: { ...process.env, ...(idleMs ? { SHOTKIT_IDLE_MS: String(idleMs) } : {}) },
  });
  child.unref();

  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    const pong = await ping({ timeout: 500 });
    if (pong) return pong;
    await new Promise((r) => setTimeout(r, 60));
  }
  throw new Error("daemon did not come up; retry with --no-daemon to see the error");
}
