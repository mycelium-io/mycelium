// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Finding a Chromium to drive.
 *
 * Playwright pins an exact browser build per release and refuses anything else,
 * which is a good property for a test suite and a bad one for a utility that has
 * to run on whatever the host already has — a CI image ships one build, a
 * developer's laptop another, and neither is worth a re-download to take a
 * screenshot. So a failed `launch()` falls through to whatever browser is
 * actually on disk, driven by `executablePath`.
 *
 * Order of preference: `SHOTKIT_CHROMIUM`, the headless shell (smaller, faster
 * to start), full Chromium from the Playwright cache, then a system install.
 */

import { existsSync, readdirSync } from "node:fs";
import { homedir, platform } from "node:os";
import { join } from "node:path";

const BROWSERS_DIR = process.env.PLAYWRIGHT_BROWSERS_PATH ||
  (platform() === "darwin" ? join(homedir(), "Library/Caches/ms-playwright") : join(homedir(), ".cache/ms-playwright"));

/** Per-platform binary path inside one downloaded browser directory. */
const INNER = {
  chromium_headless_shell: {
    linux: "chrome-linux/headless_shell",
    darwin: "chrome-mac/headless_shell",
  },
  chromium: {
    linux: "chrome-linux/chrome",
    darwin: "chrome-mac/Chromium.app/Contents/MacOS/Chromium",
  },
};

const SYSTEM = {
  darwin: [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
  ],
  linux: ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome", "/opt/pw-browsers/chromium"],
};

/** Newest build first, so a cache with several downloads picks the current one. */
function cached(prefix) {
  if (!existsSync(BROWSERS_DIR)) return [];
  const inner = INNER[prefix]?.[platform()];
  if (!inner) return [];
  return readdirSync(BROWSERS_DIR)
    .filter((d) => d.startsWith(`${prefix}-`))
    .sort((a, b) => Number(b.split("-").pop()) - Number(a.split("-").pop()))
    .map((d) => join(BROWSERS_DIR, d, inner))
    .filter((p) => existsSync(p));
}

/** @returns {string[]} candidate executables, best first */
export function candidates() {
  const os = platform();
  return [
    process.env.SHOTKIT_CHROMIUM,
    ...cached("chromium_headless_shell"),
    ...cached("chromium"),
    ...(SYSTEM[os] ?? []),
  ].filter((p) => p && existsSync(p));
}

/**
 * Launch, preferring Playwright's own resolution and falling back to a browser
 * that is merely present.
 * @param {any} pw the playwright module
 * @param {{args: string[]}} opts
 * @returns {Promise<{browser: any, channel: string}>}
 */
export async function launchChromium(pw, opts) {
  const errors = [];
  for (const channel of ["chromium-headless-shell", undefined]) {
    try {
      const browser = await pw.chromium.launch({ channel, ...opts });
      return { browser, channel: channel ?? "chromium" };
    } catch (err) {
      errors.push(err.message.split("\n")[0]);
    }
  }
  for (const executablePath of candidates()) {
    try {
      const browser = await pw.chromium.launch({ executablePath, ...opts });
      return { browser, channel: executablePath };
    } catch (err) {
      errors.push(`${executablePath}: ${err.message.split("\n")[0]}`);
    }
  }
  throw new Error(
    `no usable Chromium.\n  tried: ${errors.join("\n  tried: ")}\n` +
      "  fix: `npx playwright install chromium`, or point SHOTKIT_CHROMIUM at a binary.",
  );
}
