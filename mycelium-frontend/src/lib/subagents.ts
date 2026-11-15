// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * MOCK: an agent's subagents.
 *
 * A subagent runs inside its parent's process (Claude Code, Cursor, Codex),
 * so it posts as its parent unless the parent hands it a handle of its own.
 * That handle is the parent's with the subagent's name after a dot,
 * `builder.review`, so the link is in the name everywhere it shows: the
 * members pane lists it under its parent, and its messages read as
 * "builder › review". It's a member only while it runs.
 */

export interface SubagentName {
  parent: string;
  name: string;
}

/** The parent and own name a handle carries, when it's a subagent of one of
 *  `agents`; null for any other handle. */
export function subagentOf(handle: string, agents?: ReadonlySet<string>): SubagentName | null {
  const bare = handle.replace(/^@/, "");
  const dot = bare.indexOf(".");
  if (dot <= 0 || dot === bare.length - 1) return null;
  const parent = bare.slice(0, dot);
  if (agents && !agents.has(parent.toLowerCase())) return null;
  return { parent, name: bare.slice(dot + 1) };
}
