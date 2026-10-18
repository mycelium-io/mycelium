// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useIsClient } from "@/lib/client-hooks";
import { useTheme } from "next-themes";
import { Monitor, Moon, Sun } from "lucide-react";
import { useCustomThemes } from "@/components/custom-theme";
import { useCommands } from "@/components/keymap-provider";
import { IconButton } from "@/components/ui/icon-button";
import { clientSettingHref, setClientSetting } from "@/lib/client-settings";
import type { PaletteCommand } from "@/lib/commands";
import { CUSTOM_THEME } from "@/lib/custom-themes";
import { SYSTEM, THEMES, modeOf, type ThemeMode } from "@/lib/themes";

interface Option {
  /** The next-themes id, or the custom theme's own id for one of yours. */
  value: string;
  label: string;
  mode: ThemeMode;
  custom?: boolean;
}

/** A theme's icon: a moon for a dark one, a sun for a light one. */
function ModeIcon({ mode }: { mode: ThemeMode }) {
  return mode === "dark" ? <Moon className="size-4" /> : <Sun className="size-4" />;
}

export function ThemeToggle() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  const { themes: customThemes, active: activeCustom } = useCustomThemes();
  const [open, setOpen] = useState(false);
  const mounted = useIsClient();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const groups = useMemo<[string, Option[]][]>(() => {
    const builtIn = (mode: ThemeMode) =>
      THEMES.filter((t) => t.mode === mode).map((t) => ({ value: t.id, label: t.label, mode }));
    const yours = customThemes.map((t) => ({ value: t.id, label: t.name, mode: t.mode, custom: true }));
    return [
      ["Light", builtIn("light")],
      ["Dark", builtIn("dark")],
      ["Yours", yours],
    ];
  }, [customThemes]);

  const pick = (option: Option) => {
    if (option.custom) {
      setClientSetting("appearance.custom-theme", option.value);
      setTheme(CUSTOM_THEME);
    } else setTheme(option.value);
  };
  const isShowing = (option: Option) =>
    option.custom ? theme === CUSTOM_THEME && activeCustom?.id === option.value : theme === option.value;

  // Separate commands so palette search finds "Dracula" instead of "Toggle theme".
  const commands = useMemo<PaletteCommand[]>(
    () => [
      ...groups.flatMap(([, options]) =>
        options.map((option) => ({
          id: `theme.${option.value}`,
          title: `${option.label} theme`,
          group: "Preferences",
          keywords: ["theme", "appearance", "color", "dark", "light"],
          run: () => pick(option),
        })),
      ),
      {
        id: `theme.${SYSTEM}`,
        title: "Theme: match this computer",
        group: "Preferences",
        keywords: ["theme", "appearance", "color", "dark", "light"],
        run: () => setTheme(SYSTEM),
      },
    ],
    // `pick` only reads setters, so the commands change with the list alone.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [groups, setTheme],
  );
  useCommands(commands);

  const row = (selected: boolean) =>
    `flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-label transition-colors hover:bg-surface ${
      selected ? "text-accent" : "text-muted-foreground"
    }`;

  return (
    <div ref={ref} className="relative">
      <IconButton label="Theme" size="md" side="bottom" pressed={open} onClick={() => setOpen((o) => !o)}>
        {mounted ? <ModeIcon mode={modeOf(resolvedTheme, activeCustom?.mode)} /> : <span className="size-4" />}
      </IconButton>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1.5 max-h-[min(32rem,calc(100vh-4rem))] w-56 overflow-y-auto rounded-xl border border-border bg-elevated p-1 shadow-xl">
          <button
            type="button"
            onClick={() => {
              setTheme(SYSTEM);
              setOpen(false);
            }}
            className={row(theme === SYSTEM)}
          >
            <Monitor className="size-4" />
            Match this computer
          </button>
          {groups.map(([title, options]) =>
            options.length ? (
              <div key={title} role="group" aria-label={title}>
                <div className="px-2.5 pb-0.5 pt-2 text-micro text-faint">{title}</div>
                {options.map((option) => (
                  <button
                    key={`${title}-${option.value}`}
                    type="button"
                    onClick={() => {
                      pick(option);
                      setOpen(false);
                    }}
                    className={row(isShowing(option))}
                  >
                    <ModeIcon mode={option.mode} />
                    <span className="truncate">{option.label}</span>
                  </button>
                ))}
              </div>
            ) : null,
          )}
          <div className="mt-1 border-t border-border pt-1">
            <Link
              href={clientSettingHref("appearance.custom-themes")}
              onClick={() => setOpen(false)}
              className="block rounded-lg px-2.5 py-1.5 text-label text-muted-foreground transition-colors hover:bg-surface"
            >
              Your own theme…
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
