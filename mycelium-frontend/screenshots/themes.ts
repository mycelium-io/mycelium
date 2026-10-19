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
  theme: { id: string; name: string; mode: "dark" | "light"; colors: Record<string, string> };
}

/** The id the app gives a custom theme, as `lib/custom-themes.ts` makes it. */
const idOf = (name: string) => `custom-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")}`;

/** Every theme in the repo's `themes/`, or none when there is no checkout. */
export function themeFiles(): ThemeFile[] {
  const dir = join(THEMES_REPO, "themes");
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((name) => name.endsWith(".json"))
    .sort()
    .map((name) => {
      const { name: title, mode, colors } = JSON.parse(readFileSync(join(dir, name), "utf8"));
      return { file: name.slice(0, -".json".length), theme: { id: idOf(title), name: title, mode, colors } };
    });
}
