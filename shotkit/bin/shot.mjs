#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * `shot` — the command line.
 *
 * Deliberately thin. Parsing argv into a spec and handing it to a daemon that
 * already has a browser open is the whole of the fast path, so this file imports
 * nothing but node builtins until it knows it has to do the work itself
 * (`--no-daemon`, or no daemon reachable). Pulling Playwright in here would put
 * a fixed cost on every invocation, including `shot --help`.
 *
 * stdout is the artifact and stderr is the commentary: a bare `shot` prints the
 * absolute path and nothing else, so `$(shot term …)` is a usable expression,
 * while timings and warnings go to stderr where they cannot corrupt it.
 */

import { spawn } from "node:child_process";
import { platform } from "node:os";
import { resolve } from "node:path";
import { helpFor, parse } from "../src/args.mjs";
import { ACTION_HELP } from "../src/actions.mjs";

const OUTPUT = {
  out: { type: "string", alias: "o", value: "<path>", help: "exact output file" },
  "out-dir": { type: "string", value: "<dir>", help: "directory for generated names (default .shotkit/)" },
  name: { type: "string", value: "<slug>", help: "basename to use instead of a derived one" },
  unique: { type: "boolean", help: "append a timestamp instead of overwriting" },
  stdout: { type: "boolean", help: "write image bytes to stdout instead of a file" },
  json: { type: "boolean", help: "print the full result object as JSON" },
  format: { type: "string", value: "png|jpeg", help: "image format (default png)" },
  quality: { type: "number", help: "jpeg quality, 1-100" },
  open: { type: "boolean", help: "open the file when done" },
};

const FRAME = {
  theme: { type: "string", value: "dark|light", help: "color scheme (default dark)" },
  scale: { type: "number", help: "device pixel ratio (default 2)" },
  width: { type: "number", alias: "w", help: "viewport width" },
  height: { type: "number", alias: "h", help: "viewport height" },
  transparent: { type: "boolean", help: "omit the background (png only)" },
};

const CHROME = {
  chrome: { type: "boolean", help: "wrap the capture in browser window chrome" },
  address: { type: "string", help: "address-bar text (default: the route)" },
  "chrome-theme": { type: "string", value: "dark|light", help: "frame theme, when it differs from the app's" },
  backdrop: { type: "string", value: "<preset|css>", help: "mycelial|mycelium|dusk|ink|paper|none, or any CSS" },
  "backdrop-seed": { type: "number", help: "which network --backdrop mycelial grows" },
  padding: { type: "number", help: "gutter around the frame (default 40)" },
  radius: { type: "number", help: "corner radius (default 12)" },
  shadow: { type: "boolean", help: "drop shadow (default on)" },
};

const RESPONSIVE = {
  viewport: { type: "string", value: "<preset|WxH@S>", help: "phone|tablet|laptop|desktop|wide, or 1280x800@2" },
  viewports: { type: "string", value: "<a,b,c>", help: "shoot several presets in one run" },
  responsive: { type: "boolean", help: "shoot the standard ladder: phone, tablet, laptop, wide" },
  sheet: { type: "boolean", help: "also compose the frames into one contact sheet" },
  "sheet-only": { type: "boolean", help: "keep only the contact sheet, not the individual frames" },
  "sheet-title": { type: "string", help: "heading on the contact sheet" },
};

const DAEMON = {
  daemon: { type: "boolean", help: "use the warm background browser (default on)" },
  idle: { type: "number", value: "<ms>", help: "daemon idle timeout when starting one" },
};

const CARD = {
  title: { type: "string", help: "title bar text" },
  backdrop: { type: "string", value: "<preset|css>", help: "mycelial|mycelium|dusk|ink|paper|none, or any CSS" },
  "backdrop-seed": { type: "number", help: "which network --backdrop mycelial grows" },
  padding: { type: "number", help: "gutter around the card (default 40)" },
  radius: { type: "number", help: "corner radius (default 12)" },
  shadow: { type: "boolean", help: "drop shadow (default on)" },
  window: { type: "string", value: "mac|plain|none", help: "title bar style (default mac)" },
  "font-size": { type: "number", help: "px (default 13.5)" },
  "line-height": { type: "number", help: "unitless (default 1.55)" },
  font: { type: "string", value: "<css>", help: "font-family override" },
  cols: { type: "number", help: "fix the body to N characters wide" },
  "max-width": { type: "number", help: "px cap on the card" },
};

const PAGE = {
  "full-page": { type: "boolean", help: "capture the whole scrollable page" },
  element: { type: "string", alias: "e", value: "<sel>", help: "clip to one element" },
  wait: { type: "string", dest: "waitFor", value: "<sel>", help: "wait for a selector to be visible" },
  "wait-text": { type: "string", value: "<text>", help: "wait for text to appear in the body" },
  settle: { type: "string", value: "none|fast|full", help: "how hard to wait for a populated frame" },
  do: { type: "list", value: "<verb:arg>", help: "a navigation step; repeat for an ordered sequence" },
  click: { type: "list", dest: "clickNames", value: "<name>", help: "shorthand for --do click:<name>" },
  "action-timeout": { type: "number", value: "<ms>", help: "per-action timeout (default 15000)" },
  hide: { type: "list", value: "<sel>", help: "display:none a selector (repeatable)" },
  mask: { type: "list", value: "<sel>", help: "paint over a selector (repeatable)" },
  css: { type: "string", help: "extra stylesheet" },
  delay: { type: "number", value: "<ms>", help: "idle before shooting" },
  storage: { type: "map", value: "<k>=<v>", help: "seed localStorage (repeatable)" },
  timeout: { type: "number", value: "<ms>", help: "per-wait timeout (default 30000)" },
  offline: { type: "boolean", help: "resolve nothing but localhost — skips slow or unreachable CDNs" },
  block: { type: "list", value: "<host>", help: "fail this host's lookups immediately (repeatable)" },
};

const TERM = {
  cwd: { type: "string", value: "<dir>", help: "working directory for the command" },
  command: { type: "string", value: "<text>", help: "the command line to display, when it differs from the one run" },
  pty: { type: "boolean", help: "run under a pty so Rich emits color (default on)" },
  prompt: { type: "string", value: "<sigil>", help: "prompt sigil, or --no-prompt to hide the line" },
  "show-exit": { type: "boolean", help: "show a non-zero exit code (default on)" },
  "command-timeout": { type: "number", value: "<ms>", help: "kill the command after N ms" },
  env: { type: "map", value: "<k>=<v>", help: "extra environment (repeatable)" },
  echo: { type: "boolean", help: "include the plain-text output in --json" },
};

const CODE = {
  lang: { type: "string", help: "language id (default: from the extension)" },
  "line-numbers": { type: "boolean", help: "gutter (default on)" },
  "start-line": { type: "number", help: "number the first row as N" },
  range: { type: "string", value: "<a:b>", help: "only these lines" },
  highlight: { type: "string", value: "<n,n>", help: "emphasize these line numbers" },
};

const SESSION = {
  session: { type: "string", value: "<name>", help: "which held page to act on (default \"default\")" },
};

const APP = {
  "base-url": { type: "string", value: "<url>", help: "app origin (default: probe :3000-:3002)" },
  mock: { type: "boolean", help: "boot pnpm dev:mock and keep it warm in the daemon" },
};

const err = (m) => process.stderr.write(`${m}\n`);

const USAGE = `shot — fast screenshots of the app and of CLI output

one-shot
  shot app [route]        the running frontend (add --mock to boot dev:mock)
  shot url <url>          any URL
  shot term <command…>    run a command, shoot its terminal output
  shot text <file|->      render an existing text/ANSI capture as a terminal
  shot code <file>        a syntax-highlighted code card
  shot html <file|->      render an HTML document

responsive
  shot app / --responsive --sheet     every breakpoint, plus one image of all of them
  shot app / --viewports phone,wide   just these two

navigation — a page held open, driven step by step
  shot open /room/atlas --session r   open it and keep it
  shot do click:Negotiate --session r act on it
  shot shoot --session r              shoot it as it stands
  shot sessions | shot close --session r

daemon
  shot warm | status | stop | serve
  shot doctor | bench

stdout carries the path and nothing else, so it composes:
  open "$(shot app /room/atlas-migration --mock)"
` + `
actions (--do, and the arguments to \`shot do\` / \`shot shoot\`)${ACTION_HELP}
`;

const COMMAND_HELP = {
  app: ["shot app [route] [options]", { ...APP, ...PAGE, ...RESPONSIVE, ...CHROME, ...FRAME, ...OUTPUT, ...DAEMON }],
  url: ["shot url <url> [options]", { ...PAGE, ...RESPONSIVE, ...CHROME, ...FRAME, ...OUTPUT, ...DAEMON }],
  term: ["shot term [options] <command…>   (flags must precede the command)", { ...TERM, ...CARD, ...FRAME, ...OUTPUT, ...DAEMON }],
  text: ["shot text <file|-> [options]", { ...TERM, ...CARD, ...FRAME, ...OUTPUT, ...DAEMON }],
  code: ["shot code <file> [options]", { ...CODE, ...CARD, ...FRAME, ...OUTPUT, ...DAEMON }],
  html: ["shot html <file|-> [options]", { ...CARD, ...FRAME, ...OUTPUT, ...DAEMON }],
  open: ["shot open <route|url> [options]   — hold a page open under a name", { ...SESSION, ...APP, ...PAGE, ...RESPONSIVE, ...FRAME, ...DAEMON }],
  do: ["shot do <verb:arg…> [options]       — drive the held page", { ...SESSION, ...PAGE, ...DAEMON }],
  shoot: ["shot shoot [verb:arg…] [options]   — shoot the held page as it stands", { ...SESSION, ...PAGE, ...CHROME, ...FRAME, ...OUTPUT, ...DAEMON }],
  resize: ["shot resize --viewport <v> [options] — reframe the held page in place", { ...SESSION, ...RESPONSIVE, ...DAEMON }],
  close: ["shot close [options]", { ...SESSION, ...DAEMON }],
};

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

/** Turn parsed flags into an api.mjs spec. */
function toSpec(op, flags) {
  const spec = { op, ...flags };
  for (const local of ["daemon", "idle", "json", "open", "clickNames"]) delete spec[local];
  // `--click Foo` is sugar; the ordered `--do` list is the real interface, so
  // the shorthand lands at the end of it rather than in a second channel.
  if (flags.clickNames?.length) {
    spec.do = [...(flags.do ?? []), ...flags.clickNames.map((n) => `click:${n}`)];
  }
  if (flags.highlight) spec.highlight = String(flags.highlight).split(",").map(Number).filter(Boolean);
  if (flags.range) {
    const [a, b] = String(flags.range).split(":").map(Number);
    spec.range = [a || 1, b || Number.MAX_SAFE_INTEGER];
  }
  return spec;
}

async function runSpec(spec, flags) {
  const { SESSION_OPS } = await import("../src/api.mjs");
  const isSession = SESSION_OPS.has(spec.op);

  if (flags.daemon !== false) {
    try {
      const { ensureDaemon, send } = await import("../src/ipc.mjs");
      await ensureDaemon({ idleMs: flags.idle });
      return await send(isSession ? "session" : "shot", { spec });
    } catch (e) {
      // A failure the daemon reported is this shot's failure — retrying it in
      // this process would only lose the daemon's state (a booted mock server,
      // a warm cache) and produce a second, more confusing error.
      if (e.remote) throw e;
      if (isSession) {
        // A held page cannot survive the process that owns it, so there is no
        // meaningful in-process fallback for a session.
        throw new Error(`session commands need the daemon: ${e.message}`);
      }
      err(`[shot] daemon unavailable (${e.message}); running in-process`);
    }
  }
  const { capture, shutdown } = await import("../src/api.mjs");
  try {
    return await capture(spec, { mode: "direct", log: (m) => err(`[shot] ${m}`) });
  } finally {
    await shutdown();
  }
}

function report(result, flags) {
  const t = result.ms ?? {};
  const bits = [`${t.total}ms`];
  if (t.command) bits.push(`cmd ${t.command}ms`);
  if (t.capture) bits.push(`capture ${t.capture}ms`);
  const size = result.width ? ` · ${result.width}x${result.height}` : "";
  err(`[shot] ${result.op} · ${bits.join(" · ")} · ${result.mode ?? "daemon"}${size}`);
  if (result.meta?.exitCode) err(`[shot] command exited ${result.meta.exitCode}`);
  if (result.meta?.hint) err(`[shot] ${result.meta.hint}`);
  for (const step of result.trace ?? []) err(`[shot]   ${step.action} (${step.ms}ms)`);
  for (const shot of result.shots ?? []) err(`[shot]   ${shot.viewport} · ${shot.ms}ms · ${shot.width}x${shot.height}`);

  if (flags.json) {
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } else if (result.base64) {
    process.stdout.write(Buffer.from(result.base64, "base64"));
  } else if (result.shots && !result.path) {
    for (const shot of result.shots) if (shot.path) process.stdout.write(`${shot.path}\n`);
  } else if (result.path) {
    process.stdout.write(`${result.path}\n`);
  } else {
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  }
  if (flags.open && result.path) {
    const opener = platform() === "darwin" ? "open" : "xdg-open";
    spawn(opener, [result.path], { detached: true, stdio: "ignore" }).unref();
  }
}

async function main() {
  const [command, ...argv] = process.argv.slice(2);

  if (!command || command === "help" || command === "--help" || command === "-h") {
    const topic = argv[0];
    if (topic && COMMAND_HELP[topic]) {
      const [usage, spec] = COMMAND_HELP[topic];
      process.stdout.write(`${usage}\n\n${helpFor(spec)}\n`);
    } else {
      process.stdout.write(USAGE);
    }
    return;
  }

  if (command === "serve") {
    process.env.SHOTKIT_DAEMON_VERBOSE = "1";
    await import("../src/daemon.mjs");
    return;
  }

  if (command === "status" || command === "stop" || command === "warm") {
    const { ensureDaemon, ping, send } = await import("../src/ipc.mjs");
    if (command === "stop") {
      const alive = await ping();
      if (!alive) {
        err("[shot] no daemon running");
        return;
      }
      const res = await send("stop");
      err(`[shot] stopped pid ${res.pid}`);
      return;
    }
    if (command === "status") {
      const alive = await ping();
      if (!alive) {
        err("[shot] no daemon running");
        process.stdout.write(`${JSON.stringify({ running: false }, null, 2)}\n`);
        return;
      }
      const res = await send("status");
      process.stdout.write(`${JSON.stringify(res, null, 2)}\n`);
      return;
    }
    const { flags } = parse(argv, { ...APP, ...DAEMON });
    const t0 = Date.now();
    await ensureDaemon({ idleMs: flags.idle });
    const res = await send("warm", { mock: Boolean(flags.mock) }, { timeout: 180_000 });
    err(`[shot] warm in ${Date.now() - t0}ms`);
    process.stdout.write(`${JSON.stringify(res, null, 2)}\n`);
    return;
  }

  if (command === "sessions") {
    const result = await runSpec({ op: "sessions" }, {});
    process.stdout.write(`${JSON.stringify(result.sessions, null, 2)}\n`);
    return;
  }

  if (command === "doctor") {
    const { doctor } = await import("../src/doctor.mjs");
    await doctor();
    return;
  }

  if (command === "bench") {
    const { bench } = await import("../src/doctor.mjs");
    await bench(argv);
    return;
  }

  const entry = COMMAND_HELP[command];
  if (!entry) {
    err(`unknown command: ${command}\n`);
    process.stdout.write(USAGE);
    process.exitCode = 2;
    return;
  }
  const [, flagSpec] = entry;
  const { flags, rest } = parse(argv, flagSpec, { stopAtPositional: command === "term" });

  let spec;
  if (command === "term") {
    if (rest.length === 0) throw new Error("shot term needs a command: shot term mycelium --help");
    spec = toSpec("term", flags);
    spec.argv = rest;
  } else if (command === "open") {
    spec = toSpec("open", flags);
    const target = rest[0] ?? "/";
    if (target.startsWith("http")) spec.url = target;
    else spec.route = target;
  } else if (command === "do" || command === "shoot") {
    spec = toSpec(command === "do" ? "act" : "shoot", flags);
    // Bare positionals are actions, so the common case reads as a sentence:
    //   shot do click:Negotiate wait:.offer-grid
    spec.do = [...(spec.do ?? []), ...rest];
    if (command === "do" && spec.do.length === 0) throw new Error(`shot do needs an action${ACTION_HELP}`);
  } else if (command === "resize" || command === "close") {
    spec = toSpec(command, flags);
  } else if (command === "text") {
    const src = rest[0];
    if (!src) throw new Error("shot text needs a file, or - for stdin");
    const { readFile } = await import("node:fs/promises");
    spec = toSpec("term", flags);
    spec.text = src === "-" ? await readStdin() : await readFile(resolve(src), "utf8");
    spec.title ??= src === "-" ? "terminal" : src.split("/").pop();
    spec.name ??= `text-${(src === "-" ? "stdin" : src).split("/").pop()}`;
  } else if (command === "code") {
    if (!rest[0]) throw new Error("shot code needs a file");
    spec = toSpec("code", flags);
    spec.file = resolve(rest[0]);
  } else if (command === "html") {
    const src = rest[0];
    if (!src) throw new Error("shot html needs a file, or - for stdin");
    spec = toSpec("html", flags);
    if (src === "-") spec.html = await readStdin();
    else spec.file = resolve(src);
  } else if (command === "url") {
    if (!rest[0]) throw new Error("shot url needs a URL");
    spec = toSpec("url", flags);
    spec.url = rest[0];
  } else {
    spec = toSpec("app", flags);
    spec.route = rest[0] ?? "/";
  }

  const result = await runSpec(spec, flags);
  report(result, flags);
}

main().catch((e) => {
  err(`[shot] ${e?.stack ?? e}`);
  process.exit(1);
});
