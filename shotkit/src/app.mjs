// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Finding — or starting — the app to point the camera at.
 *
 * `--mock` boots `pnpm dev:mock` and hands the process to the daemon rather than
 * to the request: a Next dev server takes seconds to come up, and an agent
 * taking six screenshots of six routes should pay that once. The server lives
 * until `shot stop` or the daemon's idle timeout, and dies with it.
 */

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { createServer } from "node:net";
import { REPO_ROOT } from "./engine.mjs";

export const FRONTEND_DIR = `${REPO_ROOT}/mycelium-frontend`;

/** Ports a dev server is plausibly already sitting on. */
const PROBE_PORTS = [3000, 3001, 3002];

/**
 * Next records its own address here, which beats probing: a dev server started
 * with `--port 0`, or by a previous daemon, is on a port nothing would guess.
 * The file outlives the process, so the URL is still checked before it is used.
 */
function lockedDevServer() {
  try {
    const lock = JSON.parse(readFileSync(`${FRONTEND_DIR}/.next/dev/lock`, "utf8"));
    return lock.appUrl ?? (lock.port ? `http://localhost:${lock.port}` : null);
  } catch {
    return null;
  }
}

async function alive(url, timeoutMs = 700) {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const res = await fetch(url, { redirect: "manual", signal: ac.signal });
    return res.status > 0;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function freePort() {
  return new Promise((res, rej) => {
    const srv = createServer();
    srv.on("error", rej);
    srv.listen(0, () => {
      const addr = srv.address();
      const port = typeof addr === "object" && addr ? addr.port : 0;
      srv.close(() => res(port));
    });
  });
}

async function waitForServer(url, timeoutMs, check) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    check?.();
    if (await alive(url, 1000)) return;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`dev:mock never answered at ${url} (${timeoutMs}ms)`);
}

/** @type {{proc: import("node:child_process").ChildProcess | null, url: string, adopted: boolean} | null} */
let mockServer = null;

export function mockStatus() {
  if (!mockServer) return { running: false };
  return { running: true, url: mockServer.url, pid: mockServer.proc?.pid ?? null, adopted: mockServer.adopted };
}

/** Next refuses a second dev server per directory, and says where the first is. */
const ALREADY_RUNNING = /Another next dev server is already running[\s\S]*?(http:\/\/localhost:\d+)/;

/**
 * Boot `pnpm dev:mock`, or attach to the one that is already up.
 *
 * Attaching matters more than it looks: a dev server that outlived a previous
 * daemon still holds the directory, and Next will refuse to start a second one
 * rather than pick another port. Treating that refusal as an address — it names
 * the running server's URL — turns the one failure mode this has into the
 * fast path.
 */
export async function ensureMockServer({ log = () => {} } = {}) {
  if (mockServer && (mockServer.adopted || !mockServer.proc?.killed)) {
    if (await alive(`${mockServer.url}/`, 1500)) return mockServer.url;
    mockServer = null;
  }

  const locked = lockedDevServer();
  if (locked && (await alive(`${locked}/`, 1500))) {
    log(`attaching to the dev server already running at ${locked}`);
    mockServer = { proc: null, url: locked, adopted: true };
    return locked;
  }

  const port = await freePort();
  log(`booting dev:mock on :${port}`);
  const proc = spawn("pnpm", ["dev:mock", "--port", String(port)], {
    cwd: FRONTEND_DIR,
    env: { ...process.env, MYCELIUM_UI_MOCK: "1", PORT: String(port) },
    stdio: ["ignore", "pipe", "pipe"],
    // Its own process group: `pnpm` is a wrapper, and signalling only the
    // wrapper orphans the next-server child, which then holds the directory
    // against every later boot.
    detached: true,
  });

  let transcript = "";
  const watch = (d) => {
    transcript += d;
    if (process.env.SHOTKIT_DAEMON_VERBOSE) process.stderr.write(d);
  };
  proc.stdout?.on("data", watch);
  proc.stderr?.on("data", watch);

  // Address the dev server as `localhost`, not `127.0.0.1`: Next's dev-server
  // cross-origin guard only allow-lists `localhost`, so a browser 403s on every
  // /_next/* chunk over the IP and the app never hydrates.
  const url = `http://localhost:${port}`;
  try {
    await waitForServer(`${url}/`, 120_000, () => {
      const m = ALREADY_RUNNING.exec(transcript);
      if (m) throw Object.assign(new Error("adopt"), { adoptUrl: m[1] });
    });
  } catch (e) {
    killTree(proc);
    if (e.adoptUrl && (await alive(`${e.adoptUrl}/`, 3000))) {
      log(`attaching to the dev server already running at ${e.adoptUrl}`);
      mockServer = { proc: null, url: e.adoptUrl, adopted: true };
      return e.adoptUrl;
    }
    throw new Error(`dev:mock did not come up.\n${transcript.slice(-800)}`);
  }

  mockServer = { proc, url, adopted: false };
  log("dev:mock ready");
  return url;
}

function killTree(proc) {
  if (!proc?.pid) return;
  try {
    // Negative pid signals the whole group, so the next-server child goes too.
    process.kill(-proc.pid, "SIGTERM");
  } catch {
    try {
      proc.kill("SIGTERM");
    } catch {
      /* already gone */
    }
  }
}

export function stopMockServer() {
  if (!mockServer) return false;
  if (mockServer.proc) killTree(mockServer.proc);
  mockServer = null;
  return true;
}

/**
 * @param {{baseUrl?:string, mock?:boolean, log?:(m:string)=>void}} opts
 * @returns {Promise<string>}
 */
export async function resolveBaseUrl(opts = {}) {
  if (opts.baseUrl) return opts.baseUrl.replace(/\/$/, "");
  if (opts.mock) return ensureMockServer(opts);
  const fromEnv = process.env.SHOTKIT_APP_URL ?? process.env.MYCELIUM_UI_URL;
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  // A remembered server is still checked: a dev server can wedge or be killed
  // between shots, and returning its URL anyway turns that into a 30s
  // navigation timeout instead of a clear "no app found".
  if (mockServer && (await alive(`${mockServer.url}/`, 1500))) return mockServer.url;
  mockServer = null;
  const locked = lockedDevServer();
  if (locked && (await alive(`${locked}/`))) return locked;
  for (const port of PROBE_PORTS) {
    const url = `http://localhost:${port}`;
    if (await alive(`${url}/`)) return url;
  }
  throw new Error(
    `no app found${locked ? ` (${locked} from .next/dev/lock is not answering)` : ""} ` +
      `on ${PROBE_PORTS.map((p) => `:${p}`).join(", ")}. ` +
      "Start it, pass --base-url, or use --mock to have shotkit boot dev:mock.",
  );
}
