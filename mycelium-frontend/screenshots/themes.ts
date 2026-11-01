// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The themes repo (github.com/mycelium-io/themes) as a third consumer: one
 * picture of the app per theme file in it, written beside the file as
 * `screens/<file>.png`, so its README shows each theme as it looks.
 *
 * Every theme is shot the way a person would have it, as a custom theme the
 * app paints from the file's colors, the built-in ones included: the picture
 * is of the file, not of the app's own copy of it.
 */

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseCustomTheme, type CustomTheme } from "../src/lib/custom-themes.ts";

const HERE = dirname(fileURLToPath(import.meta.url));

/**
 * The themes repo sits beside the mycelium checkout, like the splash repo.
 * Not MYCELIUM_THEMES_DIR: that is this machine's own themes folder, which the
 * desktop app hands its UI server.
 */
export const THEMES_REPO = process.env.MYCELIUM_THEMES_REPO
  ? resolve(process.env.MYCELIUM_THEMES_REPO)
  : resolve(HERE, "..", "..", "..", "themes");

export interface ThemeFile {
  /** The file's name without `.json`, which its picture is named after. */
  file: string;
  /** The theme as the app keeps a custom one, id included. */
  theme: CustomTheme;
}

let found: ThemeFile[] | undefined;

/**
 * Every theme in the repo's `themes/` the app would load, or none when there
 * is no checkout. Each file is checked by the app's own rules: one it would
 * refuse is reported with the reasons and left out, never photographed as the
 * default theme under its name, and never stops the shots of anything else.
 * Read once, since the shot list and the targets both ask.
 */
export function themeFiles(): ThemeFile[] {
  if (found) return found;
  const dir = join(THEMES_REPO, "themes");
  found = [];
  if (!existsSync(dir)) return found;
  for (const name of readdirSync(dir).filter((n) => n.endsWith(".json")).sort()) {
    let parsed: ReturnType<typeof parseCustomTheme>;
    try {
      parsed = parseCustomTheme(readFileSync(join(dir, name), "utf8"));
    } catch (err) {
      parsed = { ok: false, errors: [String(err)] };
    }
    if (parsed.ok) found.push({ file: name.slice(0, -".json".length), theme: parsed.theme });
    else process.stderr.write(`[screenshots] skipping themes/${name}, the app wouldn't load it: ${parsed.errors.join(" ")}\n`);
  }
  return found;
}
