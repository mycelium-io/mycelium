// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * MOCK: a person's own status line, as the desktop app would read it from the
 * `[statusline]` section of `~/.mycelium/config.toml` and run it.
 *
 * Each widget is fixed text or a command the app runs on its interval, on
 * this machine only, showing the first line it prints. Nothing comes from a
 * room or the hub. A widget whose command fails or runs past its time shows a
 * dot instead of a value, and says why on hover.
 */

export type StatusIcon = "memory" | "disk" | "upload" | "ci" | "text";

export interface StatusWidget {
  /** Said after the value, the way every cell in the rail reads. */
  label: string;
  icon?: StatusIcon;
  command?: string;
  text?: string;
  every?: string;
  /** Seconds before a run counts as hung. */
  timeout?: number;
  /** Draw a percentage as a small meter too. */
  meter?: boolean;
}

export interface WidgetRun {
  /** The first line the command printed. */
  value?: string;
  ok: boolean;
  exit?: number;
  timedOut?: boolean;
  /** The first line of what it printed to stderr. */
  error?: string;
  ran: string;
}

export const CONFIG_PATH = "~/.mycelium/config.toml";

export const WIDGETS: StatusWidget[] = [
  {
    label: "RAM free",
    icon: "memory",
    command: "memory_pressure | awk '/free percentage/ {print $5}'",
    every: "30s",
    meter: true,
  },
  {
    label: "disk free",
    icon: "disk",
    command: "df -h / | awk 'NR==2 {print $4}'",
    every: "5m",
  },
  {
    label: "uploads",
    icon: "upload",
    command: "du -sh ~/.mycelium/rooms/*/uploads | awk '{s+=$1} END {print s \"M\"}'",
    every: "10m",
  },
  {
    label: "CI",
    icon: "ci",
    command: "gh run list --limit 1 --json conclusion -q '.[0].conclusion'",
    every: "2m",
    timeout: 10,
  },
];

export const RUNS: WidgetRun[] = [
  { value: "38%", ok: true, ran: "12s ago" },
  { value: "32Gi", ok: true, ran: "3m ago" },
  { value: "392M", ok: true, ran: "6m ago" },
  { ok: false, exit: 4, error: "gh: To get started with GitHub CLI, please run: gh auth login", ran: "40s ago" },
];

/** The section as it sits in the person's config file. */
export const CONFIG_TOML = `[statusline]
# Shown on this machine only. Runs nothing until you add a widget.

[[statusline.widget]]
label = "RAM free"
icon = "memory"
command = "memory_pressure | awk '/free percentage/ {print $5}'"
every = "30s"
meter = true

[[statusline.widget]]
label = "disk free"
icon = "disk"
command = "df -h / | awk 'NR==2 {print $4}'"
every = "5m"

[[statusline.widget]]
label = "uploads"
icon = "upload"
command = "du -sh ~/.mycelium/rooms/*/uploads | awk '{s+=$1} END {print s \\"M\\"}'"
every = "10m"

[[statusline.widget]]
label = "CI"
icon = "ci"
command = "gh run list --limit 1 --json conclusion -q '.[0].conclusion'"
every = "2m"
timeout = 10
`;
