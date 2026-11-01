// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef } from "react";
import useSWR from "swr";
import { useTheme } from "next-themes";
import { fetchLocalThemes, logFetchError, saveLocalTheme } from "@/lib/api";
import { setClientSetting, useClientSetting } from "@/lib/client-settings";
import { CUSTOM_DARK_CLASS, CUSTOM_THEME, themeVars, type CustomTheme } from "@/lib/custom-themes";
import { useThemeFilesStream } from "@/lib/stream-hub";
import { SYSTEM, themeById } from "@/lib/themes";

const LOCAL_THEMES = ["local-themes"] as const;

/** Read once, then again only when the app's server says the files changed
 *  (`ThemeFileSync`, on the held stream's `themes` feed). Where the app keeps
 *  no theme files (anything but the desktop app), that one answer says so and
 *  nothing asks again. */
function useLocalThemes() {
  return useSWR(LOCAL_THEMES, fetchLocalThemes, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    dedupingInterval: 500,
  });
}

/** The themes there are besides the built-in ones: this machine's theme files
 *  (where `mycelium theme add` and agents put them), then any this browser
 *  imported itself. And the one the custom theme shows. */
export function useCustomThemes(): { themes: CustomTheme[]; active: CustomTheme | undefined } {
  const [local] = useClientSetting("appearance.custom-themes");
  const [activeId] = useClientSetting("appearance.custom-theme");
  const { data: files } = useLocalThemes();
  const themes = useMemo(() => {
    const fromFiles: CustomTheme[] = files?.themes ?? [];
    const ids = new Set(fromFiles.map((t) => t.id));
    return [...fromFiles, ...local.filter((t) => !ids.has(t.id))];
  }, [files, local]);
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
  const { data: files } = useLocalThemes();

  useEffect(() => {
    if (theme !== CUSTOM_THEME) return;
    if (!active) {
      // The theme it pointed at is gone: back to Mycelium's own. Not while the
      // theme files are still loading, when one of them isn't there yet.
      if (files) setTheme("dark");
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
  }, [theme, active, files, setTheme]);

  return null;
}

/**
 * Keeps the app on the theme this machine's `~/.mycelium/theme.json` names, and
 * that file on the one picked in the app. `mycelium theme use` (or an agent
 * editing the file) switches the open app within a moment, because the app's
 * server watches the files and says so; picking a theme in the app writes the
 * file, so `mycelium theme ls` agrees. Does nothing where the app keeps no
 * theme files.
 */
export function ThemeFileSync(): null {
  const { theme, setTheme } = useTheme();
  const { themes, active } = useCustomThemes();
  const { data: files, mutate } = useLocalThemes();
  useThemeFilesStream(() => void mutate());

  // The file's pick this app last followed or wrote, so a change on either side
  // is told from the other one catching up.
  const synced = useRef<string | null | undefined>(undefined);
  const local = theme === CUSTOM_THEME ? active?.id : theme;

  useEffect(() => {
    if (!files?.available || !local) return;
    const choice = files.current;
    const known = (id: string) => id === SYSTEM || !!themeById(id) || files.themes.some((t) => t.id === id);
    const write = (id: string) => {
      synced.current = id;
      void mutate(
        saveLocalTheme(id).then((saved) => ({ ...files, current: saved })),
        { optimisticData: { ...files, current: id }, revalidate: false },
      ).catch(logFetchError("saveLocalTheme"));
    };
    if (choice !== synced.current) {
      // The file moved (or this is the first look at it): follow it.
      if (choice === null) {
        if (known(local)) write(local);
        else synced.current = null;
        return;
      }
      if (choice === local) {
        synced.current = choice;
        return;
      }
      if (choice.startsWith("custom-")) {
        // Its theme isn't in this app's list yet; try again when it is.
        if (!themes.some((t) => t.id === choice)) return;
        setClientSetting("appearance.custom-theme", choice);
        setTheme(CUSTOM_THEME);
      } else setTheme(choice);
      synced.current = choice;
      return;
    }
    // The file hasn't moved, so a different theme here is a pick made here.
    if (local !== choice && known(local)) write(local);
  }, [files, local, themes, setTheme, mutate]);

  return null;
}
