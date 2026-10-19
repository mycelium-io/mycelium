// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The seam between captured shots and the consumers that publish them: the
 * docs site (`docs/`), the splash repo (`mycelium-io.github.io/`) and the
 * themes repo (`themes/`, see `themes.ts`).
 *
 * Paths are resolved relative to this file so a capture run works from any cwd.
 * Every tree receives committed PNGs — normal doc/splash builds never touch a
 * browser, and the splash repo builds standalone.
 */

import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { THEMES_REPO, themeFiles } from "./themes.ts";

const HERE = dirname(fileURLToPath(import.meta.url));

/** mycelium-frontend/screenshots -> repo root. */
export const REPO_ROOT = resolve(HERE, "..", "..");

/** docs/ inside this repo. */
export const DOCS_DIR = resolve(REPO_ROOT, "docs");

/**
 * The splash repo sits beside the mycelium checkout. Overridable so CI (which
 * checks it out elsewhere) can point at the right path.
 */
export const SPLASH_DIR = process.env.MYCELIUM_SPLASH_DIR
  ? resolve(process.env.MYCELIUM_SPLASH_DIR)
  : resolve(REPO_ROOT, "..", "mycelium-io.github.io");

export interface Target {
  /** Absolute directory the PNG is written into. */
  dir: string;
  /** Basename (without extension) for the written file in this target. */
  name: string;
  /** Also emit an `<name>@2x.png` at full device-scale resolution. */
  retina?: boolean;
}

/**
 * Map a shot id to where its PNG(s) land. A shot with no entry here is captured
 * but not published (useful while iterating on a new fixture).
 */
export const TARGETS: Record<string, Target[]> = {
  "room-channel": [{ dir: DOCS_DIR, name: "app-room-channel", retina: true }],
  "room-board": [{ dir: DOCS_DIR, name: "app-room-board", retina: true }],
  "room-empty": [{ dir: DOCS_DIR, name: "app-room-empty", retina: true }],
  // The docs' concept and guide pages.
  "board-epic": [{ dir: DOCS_DIR, name: "app-board-epic", retina: true }],
  "thread-flow": [{ dir: DOCS_DIR, name: "app-thread-flow", retina: true }],
  "swarm-dialog": [{ dir: DOCS_DIR, name: "app-swarm", retina: true }],
  machines: [{ dir: DOCS_DIR, name: "app-machines", retina: true }],
  "metrics-usage": [{ dir: DOCS_DIR, name: "app-metrics", retina: true }],
  // The docs walkthrough. It also uses app-room-empty and app-room-board.
  "walk-name": [{ dir: DOCS_DIR, name: "walk-name", retina: true }],
  "walk-add-agent": [{ dir: DOCS_DIR, name: "walk-add-agent", retina: true }],
  "walk-task": [{ dir: DOCS_DIR, name: "walk-task", retina: true }],
  "walk-thread": [{ dir: DOCS_DIR, name: "walk-thread", retina: true }],
  // The home page's steps, each cropped to the part it's about.
  "home-add-agent": [{ dir: SPLASH_DIR, name: "step-agent", retina: true }],
  "home-room": [{ dir: SPLASH_DIR, name: "step-room", retina: true }],
  "home-thread": [{ dir: SPLASH_DIR, name: "step-task", retina: true }],
  "home-mention": [{ dir: SPLASH_DIR, name: "step-wake", retina: true }],
  "home-memory": [{ dir: SPLASH_DIR, name: "step-memory", retina: true }],
  "walk-aligner": [{ dir: DOCS_DIR, name: "walk-aligner", retina: true }],
  // The themes repo: each theme's picture, beside its file.
  ...Object.fromEntries(
    themeFiles().map(({ file }) => [`theme-${file}`, [{ dir: join(THEMES_REPO, "screens"), name: file }]]),
  ),
  // The verifier: docs/verifier.html and its engine page, each in both themes.
  ...Object.fromEntries(
    ["line", "line-sure", "show-why", "fine", "settings", "channel"].flatMap((shot) =>
      ["", "-light"].map((t) => [
        `verifier-${shot}${t}`,
        [{ dir: DOCS_DIR, name: `app-verifier-${shot}${t}`, retina: true }],
      ]),
    ),
  ),
};
