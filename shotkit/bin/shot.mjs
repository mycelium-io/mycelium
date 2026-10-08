#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * `shot` — the command line.
 *
 * Imports nothing but node builtins until it knows it has to do the work
 * itself (`--no-daemon`, or no daemon reachable): Playwright is deferred so
 * it does not add a fixed cost to every invocation, including `shot --help`.
 * Parsing argv into a spec and handing it to a daemon that already has a
 * browser open is the fast path.
 *
 * stdout is the artifact and stderr is the commentary: a bare `shot` prints the
 * absolute path and nothing else, so `$(shot term …)` is a usable expression,
 * while timings and warnings go to stderr where they cannot corrupt it.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir, platform } from "node:os";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { camel, helpFor, parse, UsageError } from "../src/args.mjs";
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
  backdrop: { type: "string", value: "<preset|css>", help: "canvas|glass|mycelium|dusk|ink|paper|none, or any CSS" },
  "backdrop-seed": { type: "number", help: "which scene --backdrop canvas|glass paints" },
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

const STAGE = {
  demo: { type: "boolean", help: "tech-demo framing: tilted in perspective on a dark stage (--tilt hero)" },
  tilt: {
    type: "string",
    value: "<preset|x,y,z>",
    help: "hero|left|right|dutch|desk|flat, or degrees x,y,z (one number = dutch only); implies --demo",
  },
  perspective: { type: "number", value: "<px>", help: "camera distance; smaller is more dramatic (default 1800)" },
  fit: { type: "number", value: "<0-1>", help: "how much of the stage the window fills (default 0.74)" },
  stage: { type: "string", value: "<WxH>", help: "stage size in CSS px (default 1920x1080)" },
  glow: { type: "boolean", help: "accent glow behind the window (default on; --no-glow)" },
  reflect: { type: "boolean", help: "a faint reflection under the window" },
  grid: { type: "boolean", help: "a faint perspective grid on the ground" },
};

const VIDEO_STAGE = {
  ...STAGE,
  backdrop: { type: "string", value: "<preset|css>", help: "the stage's ground: mycelium|dusk|ink|paper|none, or any CSS" },
  "backdrop-seed": { type: "number", help: "which scene --backdrop canvas|glass paints" },
  drift: { type: "number", value: "<deg>", help: "on a stage, swing the angle this far across the take (default 10; 0 holds still)" },
  intro: { type: "string", value: "<title|line>", help: "on a stage, open on a title card (the project's logo, a title, a line under it)" },
  outro: { type: "string", value: "<title|line>", help: "on a stage, close on a title card" },
  "title-seconds": { type: "number", value: "<s>", help: "how long each title card holds (default 2.6)" },
};

const VIDEO = {
  fps: { type: "number", help: "frames per second (default 30)" },
  format: { type: "string", value: "mp4|webm|gif", help: "container (default: the best this ffmpeg writes)" },
  quality: { type: "number", help: "frame jpeg quality, 1-100 (default 92)" },
  crf: { type: "number", help: "encoder quality; lower is better" },
  zoom: { type: "number", help: "push-in factor for zoom: and --auto-zoom (default 1.6)" },
  "auto-zoom": { type: "boolean", help: "push in on every click, and back out after" },
  cursor: { type: "boolean", help: "draw the pointer (default on)" },
  "cursor-size": { type: "number", help: "pointer height in px (default 30)" },
  "caption-at": {
    type: "string",
    value: "bottom|top",
    help: "where caption: text sits (default bottom; top when the bottom is where the action is)",
  },
  accent: { type: "string", value: "<css>", help: "click-ring color (default: the theme's accent)" },
  "move-ms": { type: "number", help: "how long the pointer takes to travel (default 620)" },
  dwell: { type: "number", value: "<ms>", help: "beat after each action (default 620)" },
  "zoom-ms": { type: "number", help: "push-in duration (default 620)" },
  "press-ms": { type: "number", help: "how long the button stays down (default 110)" },
  "lead-in": { type: "number", value: "<ms>", help: "still frames before the first action (default 500)" },
  tail: { type: "number", value: "<ms>", help: "still frames after the last one (default 1000)" },
  "max-seconds": { type: "number", help: "stop the take at N seconds (default 90)" },
  capture: { type: "string", value: "screencast|shots", help: "frame source (default screencast)" },
  scale: { type: "number", help: "device pixel ratio (default 1, even for a preset that implies 2)" },
  viewport: { type: "string", value: "<preset|WxH@S>", help: "phone|tablet|laptop|desktop|wide, or 1280x800@2" },
};

/** How a soundtrack is mixed, for `shot sound` and `shot video --sound`. */
const MIX = {
  bed: { type: "string", value: "<file>", help: "music or ambience under the clicks, looped or cut to fit (needs a full ffmpeg)" },
  "bed-db": { type: "number", value: "<dB>", help: "the bed under the clicks; moves the bed alone (default -6)" },
  target: { type: "number", value: "<LUFS>", help: "bed and clicks together, before --bed-db (default -19)" },
  "click-db": { type: "number", value: "<dB>", help: "clicks louder or softer (default 0)" },
  "key-db": { type: "number", value: "<dB>", help: "keystrokes louder or softer (default 0)" },
  foley: { type: "boolean", help: "the clicks and keys (default on; --no-foley for the bed alone)" },
  wav: { type: "string", value: "<path>", help: "also keep the soundtrack as a WAV" },
};

const SOUND = {
  sound: { type: "boolean", help: "give the take a soundtrack: its clicks and keys, over --bed if given" },
  ...MIX,
};

const DAEMON = {
  daemon: { type: "boolean", help: "use the warm background browser (default on)" },
  idle: { type: "number", value: "<ms>", help: "daemon idle timeout when starting one" },
};

const CARD = {
  title: { type: "string", help: "title bar text" },
  backdrop: { type: "string", value: "<preset|css>", help: "canvas|glass|mycelium|dusk|ink|paper|none, or any CSS" },
  "backdrop-seed": { type: "number", help: "which scene --backdrop canvas|glass paints" },
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
  "storage-state": {
    type: "string",
    value: "<file>",
    help: "shoot signed in: a saved Playwright login (default $SHOTKIT_STORAGE_STATE)",
  },
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
  verbose: { type: "boolean", help: "on failure, print the stack too" },
  project: { type: "string", value: "<dir>", help: "the project (config, output folder) to work as" },
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
  mock: { type: "boolean", help: "boot the project's mock dev script (dev:mock) and keep it warm in the daemon" },
};

/** The project's committed flows (see src/flows.mjs), for ops that open the app. */
const FLOW = {
  flow: { type: "list", value: "<name>", help: "run a committed flow first (repeatable; shot flows lists them)" },
  setup: { type: "boolean", help: "run the project's setup flow first, when it names one (default on; --no-setup)" },
};

// A take has no still-image business: nothing is clipped to an element, masked,
// or made transparent, so those flags stay out of `shot help video`.
const { "full-page": _fullPage, element: _element, mask: _mask, ...VIDEO_PAGE } = PAGE;
const { transparent: _transparent, ...VIDEO_FRAME } = FRAME;

const err = (m) => process.stderr.write(`${m}\n`);

/**
 * `--verbose` is taken out of argv before any command parses it, so it works
 * the same after every command: a failure then prints its stack. Not after
 * `shot term`, whose line belongs to the child from its first word on; there it
 * is an ordinary flag ahead of the command.
 */
const VERBOSE_FLAG = process.argv[2] === "term" ? -1 : process.argv.indexOf("--verbose");
if (VERBOSE_FLAG !== -1) process.argv.splice(VERBOSE_FLAG, 1);
let VERBOSE = VERBOSE_FLAG !== -1 || Boolean(process.env.SHOTKIT_DEBUG || process.env.SHOT_DEBUG);

/**
 * `--project <dir>`: shoot another checkout (a worktree of main, say) without
 * cd-ing into it. It has to land before src/project.mjs is first imported,
 * which fixes the project for the process, so like --verbose it is taken out
 * of argv up front; `shot term` reads it as an ordinary flag instead.
 */
function useProject(dir) {
  if (!dir) throw new UsageError("--project needs a folder: shot app / --project ../app-main");
  const path = resolve(dir);
  if (!existsSync(path)) throw new UsageError(`--project ${dir}: no such folder`);
  process.env.SHOTKIT_PROJECT = path;
}
const PROJECT_FLAG = process.argv[2] === "term" ? -1 : process.argv.findIndex((a) => a === "--project" || a.startsWith("--project="));
const projectArg =
  PROJECT_FLAG === -1
    ? undefined
    : process.argv[PROJECT_FLAG].includes("=")
      ? process.argv.splice(PROJECT_FLAG, 1)[0].slice("--project=".length)
      : (process.argv.splice(PROJECT_FLAG, 2)[1] ?? "");

const USAGE = `shot — fast screenshots of the app and of CLI output

one-shot
  shot app [route]        the running frontend (add --mock to boot its dev:mock script)
  shot url <url>          any URL
  shot term <command…>    run a command, shoot its terminal output
  shot text <file|->      render an existing text/ANSI capture as a terminal
  shot code <file>        a syntax-highlighted code card
  shot html <file|->      render an HTML document

video
  shot video [route] --do click:X --auto-zoom      a short take, cursor and all
  shot video [route] --do click:X --sound          …with its clicks and keys heard
  shot sound <video> [--bed music.mp3]             give a take its soundtrack

responsive
  shot app / --responsive --sheet     every breakpoint, plus one image of all of them
  shot app / --viewports phone,wide   just these two

navigation — a page held open, driven step by step
  shot open /settings --session r     open it and keep it
  shot do click:Save --session r      act on it
  shot shoot --session r              shoot it as it stands
  shot sessions | shot close --session r

flows — steps the project commits for reuse (shotkit/flows/*.json)
  shot flows                          what the project ships
  shot app --flow task-drawer         run one, then shoot

daemon
  shot warm | status | stop | serve
  shot doctor | bench

stdout carries the path and nothing else, so it composes:
  open "$(shot app /settings --mock)"
A failure is one line, last: [shot] error: … — add --verbose for the stack.
--project <dir> on any command works as that checkout (a worktree of main, say).
` + `
actions (--do, and the arguments to \`shot do\` / \`shot shoot\`)${ACTION_HELP}
`;

const COMMAND_HELP = {
  app: ["shot app [route] [options]", { ...APP, ...FLOW, ...PAGE, ...RESPONSIVE, ...CHROME, ...STAGE, ...FRAME, ...OUTPUT, ...DAEMON }],
  url: ["shot url <url> [options]", { ...PAGE, ...RESPONSIVE, ...CHROME, ...STAGE, ...FRAME, ...OUTPUT, ...DAEMON }],
  term: ["shot term [options] <command…>   (flags must precede the command)", { ...TERM, ...CARD, ...STAGE, ...FRAME, ...OUTPUT, ...DAEMON }],
  text: ["shot text <file|-> [options]", { ...TERM, ...CARD, ...STAGE, ...FRAME, ...OUTPUT, ...DAEMON }],
  code: ["shot code <file> [options]", { ...CODE, ...CARD, ...STAGE, ...FRAME, ...OUTPUT, ...DAEMON }],
  html: [
    "shot html <file|-> [options]       — a page option (--do, --wait, --full-page…) opens the file as a page",
    { ...CARD, ...PAGE, ...STAGE, ...FRAME, ...OUTPUT, ...DAEMON },
  ],
  open: ["shot open <route|url> [options]   — hold a page open under a name", { ...SESSION, ...APP, ...FLOW, ...PAGE, ...RESPONSIVE, ...FRAME, ...DAEMON }],
  do: ["shot do <verb:arg…> [options]       — drive the held page", { ...SESSION, ...PAGE, ...DAEMON }],
  shoot: ["shot shoot [verb:arg…] [options]   — shoot the held page as it stands", { ...SESSION, ...PAGE, ...CHROME, ...STAGE, ...FRAME, ...OUTPUT, ...DAEMON }],
  video: [
    "shot video [route|url] [options]   — a recorded take, with a visible cursor",
    { ...APP, ...FLOW, ...VIDEO_PAGE, ...VIDEO_FRAME, ...OUTPUT, ...DAEMON, ...VIDEO, ...VIDEO_STAGE, ...SOUND },
  ],
  sound: [
    "shot sound <video> [options]       — mix its clicks and keys (from <video>.sounds.json) over --bed, and mux",
    {
      ...MIX,
      out: { type: "string", alias: "o", value: "<path>", help: "write here instead of replacing the video" },
      json: { type: "boolean", help: "print the full result object as JSON" },
    },
  ],
  resize: ["shot resize --viewport <v> [options] — reframe the held page in place", { ...SESSION, ...RESPONSIVE, ...DAEMON }],
  close: ["shot close [options]", { ...SESSION, ...DAEMON }],
};

/** `/room/checkout` is a route; anything with a scheme is a URL. */
const isUrl = (s) => /^[a-z][a-z0-9+.-]*:\/\//i.test(s);

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

/** Ops that open a browser context, and so can load a saved login. */
const CONTEXT_OPS = new Set(["app", "url", "open", "video"]);

/**
 * The saved-login file as an absolute path, resolved here in the caller's
 * working directory: the daemon runs elsewhere, so a relative path must not
 * reach it. `~` is expanded because the documented way to make the file
 * (`npx playwright open --save-storage=...`) leaves it under the home dir.
 */
function storageStatePath(value) {
  if (!value) return undefined;
  const expanded = value === "~" || value.startsWith("~/") ? homedir() + value.slice(1) : value;
  return resolve(expanded);
}

/** Turn parsed flags into an api.mjs spec. */
/**
 * `--bed` and `--wav` as absolute paths, resolved here in the caller's working
 * directory: the daemon runs elsewhere, so a relative path must not reach it.
 */
function withLocalPaths(flags) {
  return {
    ...flags,
    ...(flags.bed ? { bed: resolve(flags.bed) } : {}),
    ...(flags.wav ? { wav: resolve(flags.wav) } : {}),
  };
}

/** The soundtrack's numbers, on stderr beside the take's. */
function reportSound(sound, ms) {
  if (!sound) return;
  const f = (n) => (Number.isFinite(n) ? n.toFixed(1) : "-inf");
  err(
    `[shot] sound · ${ms != null ? `${ms}ms · ` : ""}${sound.cues} cues${sound.bed ? " + bed" : ""} · ` +
      `${f(sound.lufs)} LUFS · true peak ${f(sound.truePeakDb)} dBTP`,
  );
}

function toSpec(op, flags) {
  const spec = { op, ...withLocalPaths(flags) };
  delete spec.storageState;
  if (CONTEXT_OPS.has(op)) {
    const state = storageStatePath(flags.storageState ?? process.env.SHOTKIT_STORAGE_STATE);
    if (state) spec.storageState = state;
  }
  for (const local of ["daemon", "idle", "json", "open", "clickNames", "flow", "setup"]) delete spec[local];
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

/** Which flow a `--do` step (1-based) came from, so a failing one can say. */
let blameStep = (_n) => null;

/**
 * Put the flows a capture asked for (`--flow`), behind the project's setup
 * flow, ahead of the spec: their steps run first, their storage is overridden
 * by `--storage`, and their route, viewport and theme apply only where the
 * command line names none. The setup flow is for the app, so a URL skips it.
 *
 * @param {Record<string, any>} spec @param {Record<string, any>} flags
 * @param {string | undefined} target the route or URL typed, if any
 */
async function withFlows(spec, flags, target) {
  const { SETUP_FLOW } = await import("../src/project.mjs");
  const isApp = !spec.url;
  const names = [...(isApp && SETUP_FLOW && flags.setup !== false ? [SETUP_FLOW] : []), ...(flags.flow ?? [])];
  if (!names.length) return spec;
  const { flowOfStep, loadFlows, resolveFlows } = await import("../src/flows.mjs");
  const flow = resolveFlows(names, loadFlows());
  blameStep = (n) => flowOfStep(n, flow.segments);
  const framed = ["viewport", "viewports", "responsive", "width", "height"].some((k) => spec[k] !== undefined);
  return {
    ...spec,
    storage: { ...flow.storage, ...(spec.storage ?? {}) },
    do: [...flow.do, ...(spec.do ?? [])],
    ...(isApp && !target && flow.route ? { route: flow.route } : {}),
    ...(!framed && flow.viewport ? { viewport: flow.viewport } : {}),
    ...(spec.theme === undefined && flow.theme ? { theme: flow.theme } : {}),
  };
}

/** `shot flows`: what the project ships, so an agent finds them before writing its own. */
async function listFlows(argv) {
  const { flags } = parse(argv, { json: OUTPUT.json });
  const { FLOWS_DIR, PROJECT_ROOT, SETUP_FLOW } = await import("../src/project.mjs");
  const { loadFlows } = await import("../src/flows.mjs");
  const flows = [...loadFlows().values()].map(({ file, ...f }) => ({ ...f, setup: f.name === SETUP_FLOW }));
  if (flags.json) {
    process.stdout.write(`${JSON.stringify(flows, null, 2)}\n`);
    return;
  }
  const where = FLOWS_DIR.startsWith(`${PROJECT_ROOT}/`) ? FLOWS_DIR.slice(PROJECT_ROOT.length + 1) : FLOWS_DIR;
  if (!flows.length) {
    err(`[shot] no flows in ${where}/ — see "Flows" in the shotkit README`);
    return;
  }
  const width = Math.max(...flows.map((f) => f.name.length));
  for (const f of flows) {
    const notes = [f.setup && "setup, runs first on every app capture", f.uses?.length && `uses ${f.uses.join(", ")}`, f.route]
      .filter(Boolean)
      .join(" · ");
    process.stdout.write(`${f.name.padEnd(width)}  ${f.description ?? ""}${notes ? `  (${notes})` : ""}\n`);
  }
  err(`[shot] ${flows.length} in ${where}/ · shot app --flow <name>`);
}

async function runSpec(spec, flags) {
  const { SESSION_OPS } = await import("../src/api.mjs");
  const isSession = SESSION_OPS.has(spec.op);

  if (flags.daemon !== false) {
    try {
      const { ensureDaemon, send } = await import("../src/ipc.mjs");
      await ensureDaemon({ idleMs: flags.idle });
      // A take runs for as long as it runs; the default request timeout is
      // sized for a screenshot and would cut one short.
      const timeout = spec.op === "video" ? Math.max(180_000, (spec.maxSeconds ?? 90) * 1000 + 120_000) : undefined;
      return await send(isSession ? "session" : "shot", { spec }, timeout ? { timeout } : {});
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
  if (result.op === "video") {
    bits.push(`${(result.durationMs / 1000).toFixed(1)}s`, `${result.frames} frames @ ${result.fps}fps`);
    if (result.meta?.truncated) bits.push("truncated at --max-seconds");
  }
  // The checkout on camera, when known: with worktrees, two can serve the app.
  const app = result.meta?.app;
  const from = app ? ` · ${app.startsWith(`${homedir()}/`) ? `~${app.slice(homedir().length)}` : app}` : "";
  err(`[shot] ${result.op} · ${bits.join(" · ")} · ${result.mode ?? "daemon"}${size}${from}`);
  if (result.meta?.exitCode) err(`[shot] command exited ${result.meta.exitCode}`);
  if (result.meta?.hint) err(`[shot] ${result.meta.hint}`);
  // What an `eval:` read off the page. On stderr, so stdout stays the path.
  for (const step of result.meta?.trace ?? result.trace ?? []) {
    if (step.value === undefined) continue;
    err(`[shot] ${step.action.slice(0, 60)} → ${typeof step.value === "string" ? step.value : JSON.stringify(step.value)}`);
  }
  for (const step of result.trace ?? []) err(`[shot]   ${step.action} (${step.ms}ms)`);
  for (const shot of result.shots ?? []) err(`[shot]   ${shot.viewport} · ${shot.ms}ms · ${shot.width}x${shot.height}`);
  reportSound(result.sound, result.ms?.sound);

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
  if (projectArg !== undefined) useProject(projectArg);
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

  if (command === "flows") {
    await listFlows(argv);
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

  // No browser in it, so it runs here rather than in the daemon.
  if (command === "sound") {
    const { flags, rest } = parse(argv, COMMAND_HELP.sound[1]);
    if (!rest[0]) throw new Error("shot sound needs a video: shot sound .shotkit/take.mp4");
    const { addSound, soundOptions } = await import("../src/audio/soundtrack.mjs");
    const t0 = Date.now();
    const result = await addSound(resolve(rest[0]), {
      ...soundOptions(withLocalPaths(flags)),
      out: flags.out ? resolve(flags.out) : undefined,
      log: (m) => err(`[shot] ${m}`),
    });
    reportSound(result, Date.now() - t0);
    process.stdout.write(flags.json ? `${JSON.stringify(result, null, 2)}\n` : `${result.path}\n`);
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
  let parsed;
  try {
    parsed = parse(argv, flagSpec, { stopAtPositional: command === "term" });
  } catch (e) {
    if (e instanceof UsageError) throw new UsageError(`${e.message}\n  shot help ${command} lists what it takes.`);
    throw e;
  }
  const { flags, rest } = parsed;
  if (flags.verbose) VERBOSE = true;
  if (flags.project) useProject(flags.project);
  delete flags.verbose;
  delete flags.project;

  let spec;
  if (command === "term") {
    if (rest.length === 0) throw new Error("shot term needs a command: shot term git --help");
    spec = toSpec("term", flags);
    spec.argv = rest;
  } else if (command === "open") {
    spec = toSpec("open", flags);
    const target = rest[0] ?? "/";
    if (isUrl(target)) spec.url = target;
    else spec.route = target;
    spec = await withFlows(spec, flags, rest[0]);
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
    // A document that loads its fonts, runs a script, or has to be clicked
    // through is a page, not a card: given anything a page takes, it is opened
    // from disk the way `shot url` opens one, so its relative paths resolve and
    // --do runs against it.
    const pageFlags = Object.entries(PAGE).map(([name, s]) => s.dest ?? camel(name));
    if (pageFlags.some((f) => flags[f] !== undefined)) {
      if (src === "-") throw new UsageError("shot html - (stdin) is shot as a card; page options need a file");
      spec = toSpec("url", flags);
      spec.url = pathToFileURL(resolve(src)).href;
    } else {
      spec = toSpec("html", flags);
      if (src === "-") spec.html = await readStdin();
      else spec.file = resolve(src);
    }
  } else if (command === "video") {
    spec = toSpec("video", flags);
    const target = rest[0] ?? "/";
    if (isUrl(target)) spec.url = target;
    else spec.route = target;
    spec = await withFlows(spec, flags, rest[0]);
  } else if (command === "url") {
    if (!rest[0]) throw new Error("shot url needs a URL");
    spec = toSpec("url", flags);
    spec.url = rest[0];
  } else {
    spec = toSpec("app", flags);
    spec.route = rest[0] ?? "/";
    spec = await withFlows(spec, flags, rest[0]);
  }

  const result = await runSpec(spec, flags);
  report(result, flags);
}

main().catch((e) => {
  // What went wrong, once, at the end of the output where `| tail -1` keeps it.
  // A stack says nothing to someone who mistyped a flag, and Playwright's call
  // log is detail; --verbose (or SHOTKIT_DEBUG=1) brings both back, first.
  let message = String(e?.message ?? e).replace(/^(Error: )+/, "");
  const cut = message.indexOf("\nCall log:");
  if (cut !== -1) message = message.slice(0, cut).trimEnd();
  const step = /^step (\d+), /.exec(message);
  if (step) {
    // Combined with the flows' steps, the number alone points at the wrong line.
    const from = blameStep(Number(step[1]));
    if (from) message = `${from.flow ? `flow ${from.flow}, ` : ""}${message.replace(/^step \d+/, `step ${from.step}`)}`;
  }
  if (VERBOSE && e?.stack) err(String(e.stack));
  err(`[shot] error: ${message}`);
  process.exit(e instanceof UsageError ? 2 : 1);
});
