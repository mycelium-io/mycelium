// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo } from "react";
import { useTheme } from "next-themes";
import { useClientSetting } from "@/lib/client-settings";
import { CUSTOM_DARK_CLASS, CUSTOM_THEME, themeVars, type CustomTheme } from "@/lib/custom-themes";

/** The imported themes, and the one the custom theme shows (if any). */
export function useCustomThemes(): { themes: CustomTheme[]; active: CustomTheme | undefined } {
  const [themes] = useClientSetting("appearance.custom-themes");
  const [activeId] = useClientSetting("appearance.custom-theme");
  const active = useMemo(() => themes.find((t) => t.id === activeId), [themes, activeId]);
  return { themes, active };
}

/**
 * Paints the custom theme: while it's picked, its colors are set on <html>
 * (next-themes has already put `theme-custom` there), with the dark class when
 * it's a dark theme. Every variable it set is taken off again when another
 * theme is picked, so a built-in theme's own values show through.
 */
export function CustomThemeStyle(): null {
  const { theme, setTheme } = useTheme();
  const { active } = useCustomThemes();

  useEffect(() => {
    if (theme !== CUSTOM_THEME) return;
    // The theme it pointed at was removed: go back to Mycelium's own.
    if (!active) {
      setTheme("dark");
      return;
    }
    const root = document.documentElement;
    const vars = themeVars(active);
    for (const [name, value] of Object.entries(vars)) root.style.setProperty(name, value);
    root.classList.toggle(CUSTOM_DARK_CLASS, active.mode === "dark");
    return () => {
      for (const name of Object.keys(vars)) root.style.removeProperty(name);
      root.classList.remove(CUSTOM_DARK_CLASS);
    };
  }, [theme, active, setTheme]);

  return null;
}
