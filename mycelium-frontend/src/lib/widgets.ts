// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The person's own widgets: `[statusline]` in this computer's
 * `~/.mycelium/config.toml`, run by the desktop app on this computer
 * (`mycelium/desktop/widgets.py`). The page only reads what they last said;
 * it can't name a command, and nothing here comes from a room or the hub.
 */

import useSWR from "swr";
import { appCall, useHasAppSettings } from "@/lib/desktop-app";

/** A theme color by name, never hex, so every theme still reads. */
export type WidgetColor = "accent" | "green" | "yellow" | "red" | "muted";
/** A widget's dot: the app's own `StatusDot` tones. */
export type WidgetTone = "ok" | "warn" | "bad" | "off";

/** What sets how a widget looks: from its config, and from a run's JSON over it.
 *  The desktop app has already left out anything that isn't one of these. */
export interface WidgetLook {
  /** A Lucide icon's kebab-case name, or one emoji. */
  icon?: string | null;
  color?: WidgetColor | null;
  state?: WidgetTone | null;
  /** 0 to 100. In the config, `true` reads a percentage from the text. */
  meter?: number | boolean | null;
  /** Markdown, a few lines. */
  tooltip?: string | null;
}

/** How a widget's command last went. */
export interface WidgetRun {
  ok: boolean;
  /** The first line it printed, or the `text` of the JSON it printed. */
  value: string | null;
  /** What the JSON it printed set for this run. */
  fields?: WidgetLook;
  /** Why a field it printed was left out. */
  notes?: string[];
  exit: number | null;
  timed_out: boolean;
  /** The first line it printed to stderr, when it failed. For a command kept
   *  running, the last line, once it has stopped. */
  error: string | null;
  /** When it finished, as an ISO time; for a command kept running and running
   *  now, when it started. */
  ran_at: string | null;
  /** Whether it's running now: only a command kept running (`every = "always"`) is. */
  running?: boolean;
}

export interface Widget extends WidgetLook {
  label: string;
  command: string | null;
  text: string | null;
  /** `"30s"`, `"5m"`, or `"always"` for a command kept running while the app is open. */
  every: string;
  timeout: number;
  /** Why a field in its config was left out. */
  notes?: string[];
  /** Its last run; null before its first, and for fixed text. */
  run: WidgetRun | null;
}

export interface Widgets {
  /** The config file they're read from. */
  config: string;
  /** Why the file's `[statusline]` couldn't be read, when it couldn't. */
  error: string | null;
  widgets: Widget[];
}

/** How often the page asks the app for the latest runs. */
const EVERY_MS = 5000;

/** The widgets as the app last ran them; null outside the desktop app and
 *  until the app has said. */
export function useWidgets(): Widgets | null {
  const app = useHasAppSettings();
  const { data } = useSWR<Widgets | null>(app ? ["app", "widgets"] : null, () => appCall<Widgets | null>("widgets"), {
    refreshInterval: EVERY_MS,
    revalidateOnFocus: true,
  });
  return data ?? null;
}

/** Whether a widget's command is kept running rather than run on an interval. */
export function keptRunning(widget: Widget): boolean {
  return widget.every === "always";
}

/** What a widget shows now: its text, its value, or why it has none. A
 *  command kept running shows the last line it printed while it runs, and
 *  why it stopped (its last stderr line, when it printed one) once it has. */
export type WidgetState =
  | { kind: "value"; value: string }
  | { kind: "failed" }
  | { kind: "hung" }
  | { kind: "stopped"; reason: string | null }
  | { kind: "waiting" };

export function widgetState(widget: Widget): WidgetState {
  if (widget.text !== null) return { kind: "value", value: widget.text };
  const run = widget.run;
  if (!run) return { kind: "waiting" };
  if (run.running) return { kind: "value", value: run.value ?? "Running" };
  if (keptRunning(widget) && !run.ok) return { kind: "stopped", reason: run.error };
  if (run.timed_out) return { kind: "hung" };
  if (!run.ok) return { kind: "failed" };
  return { kind: "value", value: run.value ?? "" };
}

/** A percentage in `value` (`"38%"`, `"**38.5**"`), for a meter; null when there isn't one. */
export function percent(value: string): number | null {
  const n = parseFloat(value.replace(/[*`_]/g, ""));
  return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : null;
}

/** How a widget looks now: its config, with its last good run's fields over it. */
export interface Look {
  icon: string | null;
  color: WidgetColor | null;
  state: WidgetTone | null;
  /** The bar's fill, 0 to 100; null for no bar. */
  meter: number | null;
  tooltip: string | null;
}

export function lookOf(widget: Widget): Look {
  const ran = widget.run?.ok ? (widget.run.fields ?? {}) : {};
  const pick = <K extends keyof WidgetLook>(k: K): WidgetLook[K] | null => ran[k] ?? widget[k] ?? null;
  const state = widgetState(widget);
  const meterField = pick("meter");
  const meter =
    typeof meterField === "number"
      ? Math.max(0, Math.min(100, meterField))
      : meterField === true && state.kind === "value"
        ? percent(state.value)
        : null;
  // A command kept running and running now is ok unless its config says otherwise.
  const running = widget.run?.running ? "ok" : null;
  return {
    icon: pick("icon") as string | null,
    color: pick("color") as WidgetColor | null,
    state: (pick("state") as WidgetTone | null) ?? running,
    meter,
    tooltip: pick("tooltip") as string | null,
  };
}

/** Every field the app left out, from the config and the last run, for Settings. */
export function notesOf(widget: Widget): string[] {
  return [...(widget.notes ?? []), ...(widget.run?.notes ?? [])];
}
