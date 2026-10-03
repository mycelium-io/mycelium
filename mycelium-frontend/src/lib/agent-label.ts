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

/**
 * The word beside an agent's name in the chat: the engine's kind, `a2a` for a
 * bridged service, and for an agent CLI the CLI itself where it was recorded
 * (`codex`, `claude`), else just `agent`. Never the adapter: `claude_code` is
 * how a herdr agent takes part, whatever CLI it runs.
 */
export function agentTag(a: Pick<AgentSummary, "adapter" | "kind" | "framework">): string {
  if (a.adapter === "engine") return a.kind ?? "engine";
  if (a.adapter === "a2a") return "a2a";
  return a.framework ?? "agent";
}
