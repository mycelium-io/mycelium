// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * MOCK: an agent's subagents.
 *
 * A subagent runs inside its parent's process (Claude Code, Cursor, Codex),
 * so it posts as its parent unless the parent hands it a handle of its own.
 * That handle is the parent's with the subagent's name after a colon,
 * `builder:review`. No member's handle can contain a colon, so nothing a
 * person or agent is called can look like a subagent (a dot can't do this:
 * people's handles have dots, like `avery.quinn`). The members pane lists it
 * under its parent, and its messages read `review @builder:review [subagent]`.
 * It's a member only while it runs. The built version stores the parent link;
 * this mock reads it from the handle.
 */

export interface SubagentName {
  parent: string;
  name: string;
}

/** The parent and own name a handle carries, when it's a subagent of one of
 *  `agents`; null for any other handle. */
export function subagentOf(handle: string, agents?: ReadonlySet<string>): SubagentName | null {
  const bare = handle.replace(/^@/, "");
  const colon = bare.indexOf(":");
  if (colon <= 0 || colon === bare.length - 1) return null;
  const parent = bare.slice(0, colon);
  if (agents && !agents.has(parent.toLowerCase())) return null;
  return { parent, name: bare.slice(colon + 1) };
}
