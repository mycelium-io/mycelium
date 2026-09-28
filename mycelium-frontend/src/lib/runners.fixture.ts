// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { Framework, Runner } from "@/lib/api";

/** A framework as a scan reports it; override what a test cares about. */
export function framework(over: Partial<Framework> & Pick<Framework, "id" | "name">): Framework {
  return {
    command: over.id,
    path: `/usr/local/bin/${over.id}`,
    version: "1.0.0",
    installed: true,
    launchable: true,
    note: null,
    ...over,
  };
}

/** A connected machine with herdr, Claude Code and opencode installed, and codex missing. */
export function runner(over: Partial<Runner> = {}): Runner {
  return {
    id: "julias-mbp",
    label: "julias-mbp",
    owner: "julia",
    platform: "darwin-arm64",
    version: "0.14.0",
    herdr: true,
    roots: ["/Users/julia/code/atlas"],
    frameworks: [
      framework({ id: "claude", name: "Claude Code", version: "2.4.1" }),
      framework({ id: "opencode", name: "opencode", version: "0.9.3" }),
      framework({
        id: "codex",
        name: "Codex CLI",
        path: null,
        version: null,
        installed: false,
        launchable: false,
        note: "Not found on PATH.",
      }),
    ],
    agents: [],
    connected: true,
    last_seen: "2026-09-28T12:00:00Z",
    started_at: "2026-09-28T11:00:00Z",
    ...over,
  };
}
