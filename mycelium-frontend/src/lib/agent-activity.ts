// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * What an agent is doing, as the rendered view draws it: the same session its
 * terminal shows, read from the agent CLI's own session file and put in one
 * shape for every CLI. The runner on the agent's machine converts the file as
 * it grows (one converter per CLI, in `integrations/agents/`), and the desktop
 * app hands the result to this page. Like the terminal, it never reaches the
 * hub.
 *
 * Nothing here names a CLI. A converter maps the CLI's own tool names onto
 * `ToolKind`, and keeps the CLI's name in `ToolCall.name` for the JSON.
 */

import useSWR from "swr";
import { appInvoke, SCREEN_EVERY_MS } from "@/lib/desktop";

export interface AgentActivity {
  /** Bumped when a field's meaning changes, so an older app can say it's too old. */
  version: 1;
  /** The session the file belongs to. */
  session: string;
  /** The CLI's own short title for the session, when it writes one. */
  title: string | null;
  /** What the agent is doing now. The file can't tell waiting from idle,
   *  so the runner reads that off the pane. */
  state: "working" | "waiting" | "idle";
  /** What it waits on, from the pane: a permission prompt or a question. */
  waiting_on: string | null;
  /** Oldest first. A long session sends its latest items, with `earlier` set. */
  items: ActivityItem[];
  /** The session has items before the first one sent. */
  earlier: boolean;
}

export type ActivityItem = Prompt | Reply | Thinking | ToolCall | Marker;

interface Base {
  /** Stable across reads, so a view keeps what's open as items arrive. */
  id: string;
  /** ISO time it was written. */
  at: string;
}

/** What the agent was asked. */
export interface Prompt extends Base {
  kind: "prompt";
  /** A person typed it, a Mycelium wake did, or (in a sub-agent) its parent. */
  from: "person" | "wake" | "agent";
  text: string;
  /** Typed while the agent was busy, and not yet taken up. */
  queued?: boolean;
}

/** What the agent wrote back, in markdown. */
export interface Reply extends Base {
  kind: "reply";
  text: string;
}

/** The agent's reasoning. Null text when the CLI keeps only that it happened. */
export interface Thinking extends Base {
  kind: "thinking";
  text: string | null;
}

/** The kinds of tool the view knows how to draw. Anything else is `other`. */
export type ToolKind = "command" | "read" | "edit" | "write" | "search" | "web" | "agent" | "question" | "other";

export interface ToolCall extends Base {
  kind: "tool";
  tool: ToolKind;
  /** The CLI's own name for the tool, for the JSON and for `other`. */
  name: string;
  /** Its arguments in a few words: the command, the path, the query. */
  summary: string;
  status: "running" | "done" | "failed" | "interrupted";
  /** When the result came back. */
  ended_at: string | null;
  /** The result, cut to its first lines by the converter. */
  result: string | null;
  /** For `edit` and `write`: what changed. */
  change?: { path: string; added: number; removed: number; lines: string[] } | null;
  /** For `agent`: the sub-agent's own items, from its own file. */
  agent?: { description: string; items: ActivityItem[] } | null;
  /** The call and its result as the CLI wrote them, for the JSON view. */
  raw: unknown;
}

/** Something that happened to the session rather than in it. */
export interface Marker extends Base {
  kind: "marker";
  what: "compacted" | "interrupted" | "resumed";
}

export interface AgentActivityRead {
  activity: AgentActivity | null;
  /** The agent's CLI has no converter, so only its terminal shows. */
  unsupported: boolean;
  error: string | null;
}

/** What the app answers for an agent whose CLI it can't convert. */
const NO_CONVERTER = "No rendered view for this agent's CLI.";

/**
 * @`agent.handle`'s activity on this machine, read by the app while `agent`
 * is set, as often as its terminal is. Null `agent` reads nothing.
 */
export function useAgentActivity(agent: { room: string; handle: string } | null): AgentActivityRead {
  const invoke = appInvoke();
  const { data, error } = useSWR(
    agent && invoke ? ["agent-activity", agent.room, agent.handle] : null,
    async ([, room, handle]: [string, string, string]) =>
      (await appInvoke()!("agent_activity", { room, handle })) as AgentActivity | null,
    {
      refreshInterval: (latest) => (latest ? SCREEN_EVERY_MS : 0),
      refreshWhenHidden: false,
      shouldRetryOnError: false,
      dedupingInterval: SCREEN_EVERY_MS / 2,
      keepPreviousData: true,
    },
  );
  const said = error ? String(error instanceof Error ? error.message : error) : null;
  return {
    activity: data ?? null,
    unsupported: said === NO_CONVERTER,
    error: said === NO_CONVERTER ? null : said,
  };
}
