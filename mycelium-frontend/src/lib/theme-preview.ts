// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Showing a theme without choosing it: the theme menu paints what's hovered.
 *
 * A preview only paints this window's <html>: the theme's class, and a custom
 * theme's colors. It never goes through next-themes, which saves a choice and
 * tells every other window about it, so sweeping the pointer across the menu
 * writes nothing and changes no other tab, and a reload mid-hover comes back
 * on the theme that was chosen. Ending it puts <html> back exactly as it was.
 */

import { CUSTOM_CLASS, CUSTOM_DARK_CLASS, themeVars, type CustomTheme } from "@/lib/custom-themes";
import { THEME_CLASSES, themeById, type ThemeMode } from "@/lib/themes";

/** <html> as it was before the first preview, to put back. */
let saved: { className: string; style: string } | null = null;

const THEME_CLASS_NAMES = [...new Set([...Object.values(THEME_CLASSES), CUSTOM_DARK_CLASS])];

/** Paint a built-in theme by id, "system" (what this computer prefers), or a custom theme. */
export function previewTheme(target: string | CustomTheme): void {
  const root = document.documentElement;
  saved ??= { className: root.className, style: root.getAttribute("style") ?? "" };
  root.className = saved.className;
  root.classList.remove(...THEME_CLASS_NAMES);
  root.setAttribute("style", saved.style);
  // A custom theme in use paints its colors inline; they'd cover any other.
  for (const name of [...root.style].filter((n) => n.startsWith("--"))) root.style.removeProperty(name);

  let mode: ThemeMode;
  if (typeof target === "string") {
    const id =
      target === "system" ? (window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark") : target;
    const theme = themeById(id);
    if (!theme) return;
    root.classList.add(theme.className);
    mode = theme.mode;
  } else {
    root.classList.add(CUSTOM_CLASS);
    for (const [name, value] of Object.entries(themeVars(target))) root.style.setProperty(name, value);
    if (target.mode === "dark") root.classList.add(CUSTOM_DARK_CLASS);
    mode = target.mode;
  }
  root.style.colorScheme = mode;
}

/** Take the preview off, leaving <html> as the chosen theme painted it. */
export function endPreview(): void {
  if (!saved) return;
  const root = document.documentElement;
  root.className = saved.className;
  root.setAttribute("style", saved.style);
  saved = null;
}
