// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The desktop app's own settings, read and changed through its commands
 * (`mycelium-desktop/src-tauri/src/lib.rs`): where this machine's rooms live
 * (here, or on a team's hub), start at login, the model Mycelium's agents use,
 * the folders agents may start in, voice, experiences, usage stats, the
 * version, and the health check. Shown as pages of Settings in the app only;
 * a browser has none of them.
 *
 * The app answers these only while the page is its own UI, and asks on the
 * machine before a change to which hub it uses, where agents may start, the
 * model or the version. Saving most of them restarts what the app runs, and
 * the app then shows how starting is going, so a save doesn't return here.
 */

import { useSyncExternalStore } from "react";
import useSWR from "swr";
import { appInvoke } from "@/lib/desktop";

export type Mode = "hub" | "client";
export type VoiceModel = "fast" | "accurate";

/** What the app saves in its settings file (`settings.rs`). */
export interface AppSettings {
  mode: Mode;
  hubUrl: string | null;
  roots: string[];
  shareUsage?: boolean;
  voice?: boolean;
  voiceModel?: VoiceModel;
}

interface Found {
  name: string;
  path: string | null;
  bundled: boolean;
}

/** `get_state`: what the app is set to, and the programs it found. */
export interface AppState {
  settings: AppSettings | null;
  mycelium: Found;
  herdr: Found;
  home: string;
}

/** `get_model`: the key itself never comes back, only whether one is saved. */
export interface ModelView {
  model: string | null;
  base_url: string | null;
  has_key: boolean;
  key_hint: string | null;
}

export interface Framework {
  id: string;
  name: string;
  version: string | null;
  installed: boolean;
  launchable: boolean;
}

export interface Experience {
  id: string;
  title: string;
  description: string;
  open: string;
  unit: string;
  added: boolean;
  scenarios: number;
}

/** `get_hub_settings`: what a team's hub is set up with, read-only. */
export interface HubSettings {
  model: { model: string | null; provider: string | null; has_key: boolean; custom_endpoint: boolean };
  experiences: { id: string; title: string; description: string; open: string; unit: string; scenarios: number }[];
  personas_only: boolean;
  share_usage: boolean;
}

export interface Check {
  section: string;
  name: string;
  status: string;
  message: string;
  details: string[];
}

export interface AppRelease {
  tag: string;
  version: string;
  prerelease: boolean;
  published: string;
}

export interface VersionsView {
  current: string;
  releaseCandidates: boolean;
  releases: AppRelease[];
  /** Why the list is one kept from earlier, when GitHub couldn't be asked. */
  note?: string | null;
}

/** What the app answers when the person said no on the machine (`CANCELLED`). */
export const CANCELLED = "Cancelled on this machine.";

/** Whether this page can reach the app's settings: the app's own UI, in the app. */
export function hasAppSettings(): boolean {
  return appInvoke() !== null;
}

const noSubscribe = () => () => {};

/** `hasAppSettings`, for a component: false while rendering on the server. */
export function useHasAppSettings(): boolean {
  return useSyncExternalStore(noSubscribe, hasAppSettings, () => false);
}

/** Call one of the app's commands; a refusal or failure throws its message. */
export async function appCall<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const invoke = appInvoke();
  if (!invoke) throw new Error("Only the Mycelium app has these settings.");
  try {
    return (await invoke(command, args)) as T;
  } catch (e) {
    throw new Error(typeof e === "string" ? e : e instanceof Error ? e.message : String(e));
  }
}

/** A read from the app, shared by every page that asks, and refreshed when they change it. */
export function useApp<T>(command: string, args?: Record<string, unknown>) {
  const key = hasAppSettings() ? ["app", command, JSON.stringify(args ?? {})] : null;
  return useSWR<T>(key, () => appCall<T>(command, args), { revalidateOnFocus: false });
}

/** Save `settings` and restart what the app runs with them. The app asks on
 *  the machine first when they change the hub or the agents' folders. */
export async function saveAndRestart(settings: AppSettings): Promise<void> {
  await appCall("start", { settings });
}

/** The saved settings with `change` applied, the shape `start` takes. */
export function withChange(saved: AppSettings, change: Partial<AppSettings>): AppSettings {
  const next = { ...saved, ...change };
  return {
    ...next,
    hubUrl: next.mode === "client" ? (next.hubUrl ?? "").trim() : null,
    shareUsage: next.mode === "hub" && !!next.shareUsage,
    voice: next.mode === "hub" && !!next.voice,
  };
}

/** A path under the home folder as `~/…`, as people read paths; Windows shows it whole. */
export function tilde(path: string, home: string, windows = globalThis.navigator?.userAgent?.includes("Windows")): string {
  if (windows) return path;
  return home && path.startsWith(home) ? "~" + path.slice(home.length) : path;
}

/** Semver order, a prerelease (`3.0.55-rc1`) before its release: negative when `a` is older. */
export function compareVersions(a: string, b: string): number {
  const split = (v: string) => {
    const [main, pre = ""] = v.split("-", 2);
    return { nums: main.split(".").map((n) => Number(n) || 0), pre };
  };
  const [x, y] = [split(a), split(b)];
  for (let i = 0; i < 3; i++) if ((x.nums[i] ?? 0) !== (y.nums[i] ?? 0)) return (x.nums[i] ?? 0) - (y.nums[i] ?? 0);
  if (x.pre === y.pre) return 0;
  if (!x.pre) return 1;
  if (!y.pre) return -1;
  return x.pre.localeCompare(y.pre, undefined, { numeric: true });
}
