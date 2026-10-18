// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** This browser's own settings: one typed table, one storage key.
 *
 *  A client setting is a preference about how *this* person sees the app here
 *  (which key sends, their time zone, their keyboard shortcuts). It is kept in
 *  the browser, never sent to the hub, and each has a stable id so the rest of
 *  the app can link straight to it (`settingHref`). Remembered UI state (a
 *  folded rail, a dock layout, a draft) is not a setting and stays where it is.
 *
 *  Reads go through `useClientSetting`, which re-renders on a change made in
 *  this tab or another one. */

import { useCallback, useSyncExternalStore } from "react";
import { sanitizeCustomThemes, type CustomTheme } from "@/lib/custom-themes";
import { isDesktop } from "@/lib/desktop";
import { setDesktopApp, setKeyOverrides } from "@/lib/keymap";

const STORAGE_KEY = "mycelium.settings";

/** Keys each setting replaced, read once so nobody loses what they had picked. */
const LEGACY: Partial<Record<ClientSettingId, string>> = {
  "general.time-zone": "mycelium.board.tz",
};

export type SendKey = "enter" | "mod-enter";
/** How an agent's avatar is drawn: as its creature (`lib/sporelings.ts`) or its initials. */
export type AgentAvatars = "creatures" | "initials";

export interface ClientSettings {
  /** Which key sends a message; the other one starts a new line. */
  "general.send": SendKey;
  /** Whether agents appear as their creature or their initials. People always
   *  keep their initials. */
  "general.agent-avatars": AgentAvatars;
  /** The zone the board draws day boundaries in; empty means this computer's. */
  "general.time-zone": string;
  /** Keyboard shortcuts changed from their defaults, by action id. */
  "keys.overrides": Record<string, string[]>;
  /** Themes imported as JSON (`lib/custom-themes.ts`). */
  "appearance.custom-themes": CustomTheme[];
  /** Which of them the custom theme shows; empty when none is picked. */
  "appearance.custom-theme": string;
}

export type ClientSettingId = keyof ClientSettings;

export const CLIENT_DEFAULTS: ClientSettings = {
  "general.send": "enter",
  "general.agent-avatars": "creatures",
  "general.time-zone": "",
  "keys.overrides": {},
  "appearance.custom-themes": [],
  "appearance.custom-theme": "",
};

/** The settings page each client setting is on, for `settingHref`. */
const PAGE_OF: Record<ClientSettingId, SettingsPage> = {
  "general.send": "general",
  "general.agent-avatars": "general",
  "general.time-zone": "general",
  "keys.overrides": "keys",
  "appearance.custom-themes": "general",
  "appearance.custom-theme": "general",
};

export const SETTINGS_PAGES = [
  "profile",
  "general",
  "notifications",
  "keys",
  "connection",
  "room",
  "hub",
] as const;

export type SettingsPage = (typeof SETTINGS_PAGES)[number];

export function isSettingsPage(value: string | undefined): value is SettingsPage {
  return (SETTINGS_PAGES as readonly string[]).includes(value ?? "");
}

/** Where a setting (or a whole page) lives, for a link from anywhere in the app.
 *  A room setting names its room: `settingHref("room", "worker-turns", "checkout")`. */
export function settingHref(page: SettingsPage, id?: string, room?: string): string {
  const query = room ? `?room=${encodeURIComponent(room)}` : "";
  return `/settings/${page}${query}${id ? `#${id}` : ""}`;
}

export function clientSettingHref(id: ClientSettingId): string {
  return settingHref(PAGE_OF[id], id);
}

let cache: ClientSettings | null = null;
const listeners = new Set<() => void>();

function readStored(): Partial<ClientSettings> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : {};
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Partial<ClientSettings>) : {};
  } catch {
    return {};
  }
}

function migrate(stored: Partial<ClientSettings>): Partial<ClientSettings> {
  const out = { ...stored };
  for (const [id, legacy] of Object.entries(LEGACY) as [ClientSettingId, string][]) {
    if (out[id] !== undefined) continue;
    try {
      const old = window.localStorage.getItem(legacy);
      if (old) (out as Record<string, unknown>)[id] = old;
    } catch {
      // A browser refusing storage keeps the default.
    }
  }
  return out;
}

/** Drop anything stored that doesn't match its setting's type, so a hand edit
 *  or an older version can't put a wrong value in front of the app. */
function sanitize(stored: Partial<ClientSettings>): ClientSettings {
  const out: ClientSettings = { ...CLIENT_DEFAULTS, "keys.overrides": {}, "appearance.custom-themes": [] };
  if (stored["general.send"] === "enter" || stored["general.send"] === "mod-enter") {
    out["general.send"] = stored["general.send"];
  }
  if (stored["general.agent-avatars"] === "creatures" || stored["general.agent-avatars"] === "initials") {
    out["general.agent-avatars"] = stored["general.agent-avatars"];
  }
  if (typeof stored["general.time-zone"] === "string") out["general.time-zone"] = stored["general.time-zone"];
  const keys = stored["keys.overrides"];
  if (keys && typeof keys === "object" && !Array.isArray(keys)) {
    for (const [id, chords] of Object.entries(keys)) {
      if (Array.isArray(chords) && chords.every((c) => typeof c === "string")) out["keys.overrides"][id] = chords;
    }
  }
  out["appearance.custom-themes"] = sanitizeCustomThemes(stored["appearance.custom-themes"]);
  const active = stored["appearance.custom-theme"];
  if (typeof active === "string" && out["appearance.custom-themes"].some((t) => t.id === active)) {
    out["appearance.custom-theme"] = active;
  }
  return out;
}

function load(): ClientSettings {
  if (cache) return cache;
  if (typeof window === "undefined") return CLIENT_DEFAULTS;
  cache = sanitize(migrate(readStored()));
  setDesktopApp(isDesktop());
  setKeyOverrides(cache["keys.overrides"]);
  return cache;
}

function emit() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => {
    if (e.key !== STORAGE_KEY) return;
    cache = null;
    load();
    listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function getClientSetting<K extends ClientSettingId>(id: K): ClientSettings[K] {
  return load()[id];
}

export function setClientSetting<K extends ClientSettingId>(id: K, value: ClientSettings[K]): void {
  const next = { ...load(), [id]: value };
  cache = next;
  if (id === "keys.overrides") setKeyOverrides(next["keys.overrides"]);
  try {
    // Only what differs from the default is written, so a later default change
    // reaches everyone who never picked one.
    const changed: Partial<ClientSettings> = {};
    for (const key of Object.keys(next) as ClientSettingId[]) {
      if (JSON.stringify(next[key]) !== JSON.stringify(CLIENT_DEFAULTS[key])) {
        (changed as Record<string, unknown>)[key] = next[key];
      }
    }
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(changed));
    for (const legacy of Object.values(LEGACY)) window.localStorage.removeItem(legacy);
  } catch {
    // A browser refusing storage keeps the change for this tab.
  }
  emit();
}

export function resetClientSetting(id: ClientSettingId): void {
  setClientSetting(id, CLIENT_DEFAULTS[id]);
}

export function isChanged(id: ClientSettingId): boolean {
  return JSON.stringify(getClientSetting(id)) !== JSON.stringify(CLIENT_DEFAULTS[id]);
}

/** A client setting and a setter, re-rendering whenever it changes anywhere. */
export function useClientSetting<K extends ClientSettingId>(
  id: K,
): [ClientSettings[K], (value: ClientSettings[K]) => void] {
  const value = useSyncExternalStore(
    subscribe,
    () => getClientSetting(id),
    () => CLIENT_DEFAULTS[id],
  );
  const set = useCallback((next: ClientSettings[K]) => setClientSetting(id, next), [id]);
  return [value, set];
}

/** Every client setting, for export. */
export function exportClientSettings(): ClientSettings {
  return load();
}

/** Replace this browser's settings with an exported set; returns what was taken. */
export function importClientSettings(raw: unknown): ClientSettings {
  const next = sanitize(raw && typeof raw === "object" ? (raw as Partial<ClientSettings>) : {});
  for (const id of Object.keys(next) as ClientSettingId[]) setClientSetting(id, next[id] as never);
  return next;
}

/** For tests: forget the cached read. */
export function __resetClientSettingsCache(): void {
  cache = null;
}
