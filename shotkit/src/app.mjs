// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Finding — or starting — the app to point the camera at.
 *
 * `--mock` runs the project's mock dev script (`dev:mock` unless
 * `shotkit.config.json` names another) and hands the process to the daemon
 * rather than to the request: a Next dev server takes seconds to come up, and an
 * agent taking six screenshots of six routes should pay that once. The server
 * lives until `shot stop` or the daemon's idle timeout, and dies with it.
 */

import { execFileSync, spawn } from "node:child_process";
import { closeSync, existsSync, openSync, readFileSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "node:net";
import { APP_DIR, MOCK_ENV, MOCK_HEADER, MOCK_PROBE, MOCK_SCRIPT, PROJECT_ROOT } from "./project.mjs";

export const FRONTEND_DIR = APP_DIR;

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

/** @param {string} url @param {number} timeoutMs @param {() => void} [check] */
async function waitForServer(url, timeoutMs, check) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    check?.();
    if (await alive(url, 1000)) return;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`${MOCK_SCRIPT} never answered at ${url} (${timeoutMs}ms)`);
}

/**
 * Whether a running dev server is serving the mocks. A project that marks its
 * mock responses names the header (`app.mockHeader`) and a route that carries
 * it (`app.mockProbe`); a dev server in front of real data answers without it.
 * With no header configured there is no way to tell, so a running server is
 * taken at its word.
 */
async function servesMocks(url) {
  if (!MOCK_HEADER) return true;
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 5000);
  try {
    const res = await fetch(`${url}${MOCK_PROBE}`, { signal: ac.signal });
    return res.headers.get(MOCK_HEADER) === "1";
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/** A dev server holds the frontend folder and isn't the mock one: Next won't
 *  start a second, and shooting this one would show real data as the mocks. */
function notMock(url) {
  return new Error(
    `A dev server that isn't serving mocks is already running at ${url}, and Next ` +
      "allows one per folder. Stop it to shoot with --mock, or drop --mock to shoot it as it is.",
  );
}

/** @type {{proc: import("node:child_process").ChildProcess | null, url: string, adopted: boolean} | null} */
let mockServer = null;

export function mockStatus() {
  if (!mockServer) return { running: false };
  return { running: true, url: mockServer.url, dir: FRONTEND_DIR, pid: mockServer.proc?.pid ?? null, adopted: mockServer.adopted };
}

/** Next refuses a second dev server per directory, and says where the first is. */
const ALREADY_RUNNING = /Another next dev server is already running[\s\S]*?(http:\/\/localhost:\d+)/;

/**
 * How to run the mock script, by the package manager that installed the
 * frontend. pnpm handed an npm tree reinstalls it first, which its build-script
 * approval can then refuse, so each runs the tree it made.
 *
 * @param {number} port
 * @returns {[string, string[]]}
 */
export function mockCommand(port, frontendDir = FRONTEND_DIR, script = MOCK_SCRIPT) {
  if (existsSync(`${frontendDir}/node_modules/.pnpm`)) {
    return ["pnpm", [script, "--port", String(port)]];
  }
  return ["npm", ["run", script, "--", "--port", String(port)]];
}

/**
 * Boot the mock script, or attach to the one that is already up. A running dev
 * server that isn't serving mocks is refused, not attached to.
 *
 * Attaching matters more than it looks: a dev server that outlived a previous
 * daemon still holds the directory, and Next will refuse to start a second one
 * rather than pick another port. Treating that refusal as an address — it names
 * the running server's URL — turns the one failure mode this has into the
 * fast path.
 *
 * @param {{log?: (message: string) => void}} [opts]
 * @returns {Promise<string>} the base URL of a dev server that is answering
 */
export async function ensureMockServer({ log = () => {} } = {}) {
  if (mockServer && (mockServer.adopted || !mockServer.proc?.killed)) {
    if (await alive(`${mockServer.url}/`, 1500)) return mockServer.url;
    mockServer = null;
  }

  const locked = lockedDevServer();
  if (locked && (await alive(`${locked}/`, 1500))) {
    if (!(await servesMocks(locked))) throw notMock(locked);
    log(`attaching to the dev server already running at ${locked}`);
    mockServer = { proc: null, url: locked, adopted: true };
    return locked;
  }

  const port = await freePort();
  log(`booting ${MOCK_SCRIPT} on :${port}`);
  const [bin, args] = mockCommand(port);
  // Output goes to a file, not a pipe: a dev server is left running across a
  // daemon restart for the next one to adopt, and one still writing into a
  // pipe whose reader has exited stalls on its next log line.
  const logPath = join(tmpdir(), `shotkit-dev-mock-${port}.log`);
  const logFd = openSync(logPath, "w");
  const proc = spawn(bin, args, {
    cwd: FRONTEND_DIR,
    env: { ...process.env, ...MOCK_ENV, PORT: String(port) },
    stdio: ["ignore", logFd, logFd],
    // Its own process group: `pnpm` is a wrapper, and signaling only the
    // wrapper orphans the next-server child, which then holds the directory
    // against every later boot.
    detached: true,
  });

  closeSync(logFd);
  let transcript = "";
  const readLog = () => {
    try {
      transcript = readFileSync(logPath, "utf8");
    } catch {
      /* not written yet */
    }
    return transcript;
  };
  if (process.env.SHOTKIT_DAEMON_VERBOSE) log(`${MOCK_SCRIPT} output: ${logPath}`);

  // Address the dev server as `localhost`, not `127.0.0.1`: Next's dev-server
  // cross-origin guard only allow-lists `localhost`, so a browser 403s on every
  // /_next/* chunk over the IP and the app never hydrates.
  const url = `http://localhost:${port}`;
  try {
    await waitForServer(`${url}/`, 120_000, () => {
      const m = ALREADY_RUNNING.exec(readLog());
      if (m) throw Object.assign(new Error("adopt"), { adoptUrl: m[1] });
    });
  } catch (e) {
    killTree(proc);
    if (e.adoptUrl && (await alive(`${e.adoptUrl}/`, 3000))) {
      if (!(await servesMocks(e.adoptUrl))) throw notMock(e.adoptUrl);
      log(`attaching to the dev server already running at ${e.adoptUrl}`);
      mockServer = { proc: null, url: e.adoptUrl, adopted: true };
      return e.adoptUrl;
    }
    throw new Error(`${MOCK_SCRIPT} did not come up.\n${readLog().slice(-800)}`);
  }

  mockServer = { proc, url, adopted: false };
  log(`${MOCK_SCRIPT} ready`);
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
  return (await findApp(opts)).url;
}

/** `/private/tmp` and `/tmp` are one folder; compare them as one. */
const real = (p) => {
  try {
    return realpathSync(p);
  } catch {
    return p;
  }
};

/** @type {Map<string, {dir: string | null, at: number}>} */
const servedFromCache = new Map();

/**
 * The folder the process listening on a localhost URL runs from, when `lsof`
 * can say (macOS and most Linux); null otherwise. Held for a few seconds, since
 * a run of shots asks about the same server each time.
 */
export function servedFrom(url) {
  let port;
  try {
    const u = new URL(url);
    if (!["localhost", "127.0.0.1", "[::1]"].includes(u.hostname)) return null;
    port = u.port || (u.protocol === "https:" ? "443" : "80");
  } catch {
    return null;
  }
  const hit = servedFromCache.get(port);
  if (hit && Date.now() - hit.at < 15_000) return hit.dir;
  let dir = null;
  try {
    const run = (args) => execFileSync("lsof", args, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: 2000 });
    const pid = run(["-nP", `-iTCP:${port}`, "-sTCP:LISTEN", "-t"]).trim().split("\n")[0];
    if (pid) dir = /^n(.+)$/m.exec(run(["-a", "-p", pid, "-d", "cwd", "-Fn"]))?.[1] ?? null;
  } catch {
    /* no lsof, or nothing it may look at */
  }
  servedFromCache.set(port, { dir, at: Date.now() });
  return dir;
}

/**
 * A dev server found by probing, rather than named, may belong to another
 * checkout: a worktree's app shot against main's server on :3000 is the wrong
 * code with nothing to say so. Said, then, not refused — a server in a
 * container or run from elsewhere on purpose is a legitimate target.
 */
function foreignHint(url, dir) {
  if (!dir) return undefined;
  const root = real(PROJECT_ROOT);
  const d = real(dir);
  if (d === root || d.startsWith(`${root}/`)) return undefined;
  return (
    `the app at ${url} runs from ${dir}, not this project (${PROJECT_ROOT}). ` +
    "--mock boots this project's own, --base-url names another, --project shoots that folder."
  );
}

/**
 * Where the app is, which folder it is served from when that is known, and a
 * hint when it is not this project's.
 *
 * @param {{baseUrl?:string, mock?:boolean, log?:(m:string)=>void}} opts
 * @returns {Promise<{url: string, dir?: string | null, hint?: string}>}
 */
export async function findApp(opts = {}) {
  if (opts.baseUrl) return { url: opts.baseUrl.replace(/\/$/, "") };
  if (opts.mock) return { url: await ensureMockServer(opts), dir: FRONTEND_DIR };
  const fromEnv = process.env.SHOTKIT_APP_URL;
  if (fromEnv) return { url: fromEnv.replace(/\/$/, "") };
  // A remembered server is still checked: a dev server can wedge or be killed
  // between shots, and returning its URL anyway turns that into a 30s
  // navigation timeout instead of a clear "no app found".
  if (mockServer && (await alive(`${mockServer.url}/`, 1500))) return { url: mockServer.url, dir: FRONTEND_DIR };
  mockServer = null;
  const locked = lockedDevServer();
  if (locked && (await alive(`${locked}/`))) return { url: locked, dir: FRONTEND_DIR };
  for (const port of PROBE_PORTS) {
    const url = `http://localhost:${port}`;
    if (!(await alive(`${url}/`))) continue;
    const dir = servedFrom(url);
    return { url, dir, hint: foreignHint(url, dir) };
  }
  throw new Error(
    `no app found${locked ? ` (${locked} from .next/dev/lock is not answering)` : ""} ` +
      `on ${PROBE_PORTS.map((p) => `:${p}`).join(", ")}. ` +
      `Start it, pass --base-url, or use --mock to have shotkit boot ${MOCK_SCRIPT}.`,
  );
}
