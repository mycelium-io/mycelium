// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The project the camera is pointed at, and what it says about itself.
 *
 * shotkit lives in its own checkout and is run from inside someone else's, so
 * "the repo" means the caller's: `SHOTKIT_PROJECT` if set, else the git
 * top-level of the working directory, else the working directory itself. The
 * daemon is spawned with that resolved into its environment, so it agrees with
 * the client that started it however its own cwd drifts.
 *
 * A project can describe itself in `shotkit.config.json` at its root. Every
 * field is optional; with no file at all, `--mock` runs the `dev:mock` script
 * in the project root and `--backdrop canvas` is unavailable.
 *
 *   {
 *     "app": {
 *       "dir": "web",                       // where the frontend lives
 *       "mockScript": "dev:mock",           // package.json script --mock runs
 *       "mockEnv": { "UI_MOCK": "1" },      // extra env for it
 *       "mockHeader": "x-mock",             // response header proving a server is the mock one
 *       "mockProbe": "/api/health"          // a route that carries it (default "/")
 *     },
 *     "backdrop": {
 *       "canvas": "scripts/canvas.js",      // script that paints --backdrop canvas
 *       "size": "1920x1080",                // the page it paints on (default 1920x1080)
 *       "pixelated": false,                 // upscale hard-edged, for pixel art (default false)
 *       "glass": "docs/glass.js"            // a seekable scene for --backdrop glass
 *     },
 *     "stage": {                             // how a staged video's words look
 *       "fonts": "https://…/css2?family=…",  // a stylesheet for the faces below
 *       "titleFont": "\"Cormorant Garamond\", Georgia, serif",
 *       "titleStyle": "italic 600",          // weight/style of the headline
 *       "textFont": "\"IBM Plex Sans\", sans-serif",
 *       "accent": "#5dd4e0",
 *       "logo": "docs/logo.png"              // shown on the intro and outro cards
 *     }
 *   }
 */

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

function gitTopLevel(cwd) {
  try {
    return execFileSync("git", ["rev-parse", "--show-toplevel"], {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return null;
  }
}

export const PROJECT_ROOT = resolve(
  process.env.SHOTKIT_PROJECT || gitTopLevel(process.cwd()) || process.cwd(),
);

export const CONFIG_FILE = resolve(PROJECT_ROOT, "shotkit.config.json");

function loadConfig() {
  let raw;
  try {
    raw = readFileSync(CONFIG_FILE, "utf8");
  } catch {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch (e) {
    throw new Error(`${CONFIG_FILE} is not valid JSON: ${e.message}`);
  }
}

const config = loadConfig();

export const APP_DIR = resolve(PROJECT_ROOT, config.app?.dir ?? ".");
export const MOCK_SCRIPT = config.app?.mockScript ?? "dev:mock";
/** @type {Record<string, string>} */
export const MOCK_ENV = config.app?.mockEnv ?? {};
/** @type {string | null} */
export const MOCK_HEADER = config.app?.mockHeader ?? null;
export const MOCK_PROBE = config.app?.mockProbe ?? "/";
/** @type {string | null} absolute path, or null when the project names none */
export const CANVAS_PATH = config.backdrop?.canvas ? resolve(PROJECT_ROOT, config.backdrop.canvas) : null;
export const CANVAS_PIXELATED = config.backdrop?.pixelated === true;

function canvasSize(value) {
  if (value === undefined) return { width: 1920, height: 1080 };
  const m = /^(\d+)x(\d+)$/.exec(String(value).trim());
  if (!m) throw new Error(`${CONFIG_FILE}: backdrop.size takes WxH, like 1920x1080, not "${value}"`);
  return { width: Number(m[1]), height: Number(m[2]) };
}

/** The page the canvas script paints on, in CSS px; scripts often scale their scene to it. */
export const CANVAS_SIZE = canvasSize(config.backdrop?.size);
/** @type {string | null} absolute path, or null when the project names none */
export const GLASS_PATH = config.backdrop?.glass ? resolve(PROJECT_ROOT, config.backdrop.glass) : null;
/** How a staged video's captions and title cards look; every field optional. */
export const STAGE_STYLE = {
  fonts: config.stage?.fonts ?? null,
  titleFont: config.stage?.titleFont ?? null,
  titleStyle: config.stage?.titleStyle ?? null,
  textFont: config.stage?.textFont ?? null,
  accent: config.stage?.accent ?? null,
  /** @type {string | null} absolute path */
  logo: config.stage?.logo ? resolve(PROJECT_ROOT, config.stage.logo) : null,
};
