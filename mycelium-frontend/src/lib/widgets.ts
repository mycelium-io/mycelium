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

export type WidgetIcon = "memory" | "disk" | "upload" | "ci" | "text";

/** How a widget's command last went. */
export interface WidgetRun {
  ok: boolean;
  /** The first line it printed. */
  value: string | null;
  exit: number | null;
  timed_out: boolean;
  /** The first line it printed to stderr, when it failed. */
  error: string | null;
  /** When it finished, as an ISO time. */
  ran_at: string | null;
}

export interface Widget {
  label: string;
  command: string | null;
  text: string | null;
  every: string;
  timeout: number;
  icon: WidgetIcon;
  meter: boolean;
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

/** What a widget shows now: its text, its value, or why it has none. */
export type WidgetState = { kind: "value"; value: string } | { kind: "failed" } | { kind: "hung" } | { kind: "waiting" };

export function widgetState(widget: Widget): WidgetState {
  if (widget.text !== null) return { kind: "value", value: widget.text };
  const run = widget.run;
  if (!run) return { kind: "waiting" };
  if (run.timed_out) return { kind: "hung" };
  if (!run.ok) return { kind: "failed" };
  return { kind: "value", value: run.value ?? "" };
}

/** A percentage in `value` (`"38%"`, `"38.5"`), for a meter; null when there isn't one. */
export function percent(value: string): number | null {
  const n = parseFloat(value);
  return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : null;
}
