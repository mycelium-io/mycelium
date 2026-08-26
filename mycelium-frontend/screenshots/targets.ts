// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The seam between captured shots and the two consumers that publish them:
 * the docs site (`docs/`) and the splash repo (`mycelium-io.github.io/`).
 *
 * Paths are resolved relative to this file so a capture run works from any cwd.
 * Both trees receive committed PNGs — normal doc/splash builds never touch a
 * browser, and the splash repo builds standalone.
 */

import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

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
  "room-board": [
    { dir: DOCS_DIR, name: "app-room-board", retina: true },
    { dir: SPLASH_DIR, name: "app-hero", retina: true },
  ],
  "room-empty": [{ dir: DOCS_DIR, name: "app-room-empty", retina: true }],
  "room-thread": [{ dir: SPLASH_DIR, name: "app-thread", retina: true }],
  "room-memory": [{ dir: SPLASH_DIR, name: "app-memory", retina: true }],
  "room-network": [{ dir: SPLASH_DIR, name: "app-network", retina: true }],
};
