// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { AgentSummary } from "@/lib/api";

/**
 * What an agent is, in a word or two: the engine it runs, or the agent CLI.
 *
 * An agent's `adapter` is how it takes part in a room, and every agent CLI in
 * a herdr pane takes part the same way, so it says `claude_code` for Codex
 * and Pi too. Its `framework` is the CLI itself, recorded when Mycelium
 * started or enrolled it, and is what a person wants to see.
 */
export function agentLabel(a: Pick<AgentSummary, "adapter" | "kind" | "framework">): string {
  if (a.adapter === "engine") return a.kind ? `engine · ${a.kind}` : "engine";
  return a.framework ?? a.adapter;
}
