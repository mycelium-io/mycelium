// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * What an agent is doing, as the rendered view draws it: the same session its
 * terminal shows, read from the agent CLI's own session file. The runner on
 * the agent's machine converts the file as it grows (one converter per CLI, in
 * `integrations/agents/`), and the desktop app hands the result to this page.
 * Like the terminal, it never reaches the hub.
 *
 * The entries take the shapes of the Agent Client Protocol's `session/update`
 * notifications (agentclientprotocol.com, schema v1), with each stream of
 * chunks already joined into one entry, so `agent_message_chunk` arrives as
 * one `agent_message`. Mycelium doesn't speak ACP; matching its shapes keeps
 * an agent that does one small step away. What ACP has no field for is under
 * `_meta`, which ACP reserves for that.
 *
 * Nothing here names a CLI. A converter maps the CLI's own tools onto ACP's
 * `ToolKind`, and keeps the CLI's own name for the tool in `name`.
 */

import useSWR from "swr";
import { appInvoke, SCREEN_EVERY_MS } from "@/lib/desktop";

export interface AgentSession {
  /** Bumped when a field's meaning changes, so an older app can say it's too old. */
  version: 1;
  sessionId: string;
  /** Changes whenever the entries do (the runner's write count, say), so a
   *  reader can tell a new answer from the same one without comparing it. */
  rev?: string;
  /** The CLI's own short title for the session, when it writes one (ACP's `session_info_update`). */
  title: string | null;
  /**
   * What the agent is doing now. The file can't tell waiting from idle, so the
   * runner reads that off the pane; `unknown` when it can't read this CLI's
   * pane either, and then the view claims nothing.
   */
  state: "working" | "waiting" | "idle" | "unknown";
  /** What it waits on, when the pane says: the question of ACP's `session/request_permission`. */
  waitingOn: string | null;
  /** Oldest first. A long session sends its latest entries, with `earlier` set. */
  entries: SessionEntry[];
  /** The session has entries before the first one sent. */
  earlier: boolean;
}

export type SessionEntry = UserMessage | AgentMessage | AgentThought | ToolCall | Plan | Compaction;

/** What every entry carries that ACP's updates don't. */
export interface EntryMeta {
  /** Stable across reads, so a view keeps what's open as entries arrive. */
  id: string;
  /** ISO time it was written. */
  at: string;
}

export interface TextBlock {
  type: "text";
  text: string;
}

/** ACP's `user_message_chunk`, joined. */
export interface UserMessage {
  sessionUpdate: "user_message";
  content: TextBlock[];
  _meta: EntryMeta & {
    /** A person typed it, a Mycelium wake did, or (in a sub-agent) its parent. */
    from: "person" | "wake" | "agent";
    /** Typed while the agent was busy, and not yet taken up. */
    queued?: boolean;
  };
}

/** ACP's `agent_message_chunk`, joined. Markdown. */
export interface AgentMessage {
  sessionUpdate: "agent_message";
  content: TextBlock[];
  _meta: EntryMeta;
}

/** ACP's `agent_thought_chunk`, joined. */
export interface AgentThought {
  sessionUpdate: "agent_thought";
  content: TextBlock[];
  _meta: EntryMeta;
}

/** ACP's `ToolKind`. */
export type ToolKind = "read" | "edit" | "delete" | "move" | "search" | "execute" | "think" | "fetch" | "switch_mode" | "other";

/** ACP's `ToolCallStatus`. */
export type ToolCallStatus = "pending" | "in_progress" | "completed" | "failed";

/** ACP's `ToolCallContent`, less `terminal`, which a session file can't hold. */
export type ToolCallContent =
  | { type: "content"; content: TextBlock }
  | { type: "diff"; path: string; oldText: string | null; newText: string };

/** ACP's `tool_call`, with every `tool_call_update` for it applied. */
export interface ToolCall {
  sessionUpdate: "tool_call";
  toolCallId: string;
  /** Its arguments in a few words: the command, the path, the query. */
  title: string;
  /** The CLI's own name for the tool. */
  name?: string;
  kind: ToolKind;
  status: ToolCallStatus;
  /** Its result, cut to its first lines by the converter, and any change it made. */
  content?: ToolCallContent[];
  locations?: { path: string; line?: number }[];
  /** The call and its result as the CLI wrote them, for the JSON view. */
  rawInput?: unknown;
  rawOutput?: unknown;
  _meta: EntryMeta & {
    /** The person ran it, not the agent: a shell command typed into the CLI. */
    from?: "person";
    /** When the result came back. */
    endedAt?: string | null;
    /** It failed because someone stopped it. */
    interrupted?: boolean;
    /** A sub-agent's own entries, from its own file. */
    subagent?: { description: string; entries: SessionEntry[] } | null;
  };
}

/** ACP's `plan`: the agent's list of steps, sent whole each time it changes. */
export interface Plan {
  sessionUpdate: "plan";
  entries: { content: string; priority: "high" | "medium" | "low"; status: "pending" | "in_progress" | "completed" }[];
  _meta: EntryMeta;
}

/** ACP's `compaction_update`: older context was summarized. */
export interface Compaction {
  sessionUpdate: "compaction";
  _meta: EntryMeta;
}

/** Why there's no rendered view: no converter for the agent's CLI, or no session file found. */
export type Unavailable = "no_converter" | "no_session";

export interface AgentSessionRead {
  session: AgentSession | null;
  unavailable: Unavailable | null;
  error: string | null;
}

/** What the app answers when it can't give a rendered view, by reason. */
const UNAVAILABLE: Record<string, Unavailable> = {
  "No rendered view for this agent's CLI.": "no_converter",
  "Can't find this agent's session.": "no_session",
};

/**
 * @`agent.handle`'s session on this machine, read by the app while `agent`
 * is set, as often as its terminal is. Null `agent` reads nothing.
 */
export function useAgentSession(agent: { room: string; handle: string } | null): AgentSessionRead {
  const invoke = appInvoke();
  const { data, error } = useSWR(
    agent && invoke ? ["agent-session", agent.room, agent.handle] : null,
    async ([, room, handle]: [string, string, string]) =>
      (await appInvoke()!("agent_session", { room, handle })) as AgentSession | null,
    {
      refreshInterval: (latest) => (latest ? SCREEN_EVERY_MS : 0),
      refreshWhenHidden: false,
      shouldRetryOnError: false,
      dedupingInterval: SCREEN_EVERY_MS / 2,
      keepPreviousData: true,
      // A long session is most of a megabyte, asked for every second: comparing
      // it deeply each time blocked the page for 100 ms a second. Its revision
      // says whether anything changed.
      compare: (a, b) => (a && b ? revOf(a) === revOf(b) : a === b),
    },
  );
  const said = error ? String(error instanceof Error ? error.message : error) : null;
  const unavailable = said ? (UNAVAILABLE[said] ?? null) : null;
  return { session: data ?? null, unavailable, error: unavailable ? null : said };
}

/** What changes whenever anything in a session the view draws does. */
export function revOf(s: AgentSession): string {
  if (s.rev) return `${s.rev}|${s.state}|${s.waitingOn ?? ""}`;
  // Before the runner writes a revision: the last entry, and how it stands.
  const last = s.entries.at(-1);
  const status = last?.sessionUpdate === "tool_call" ? last.status : "";
  return `${s.entries.length}|${last?._meta.id ?? ""}|${status}|${s.state}|${s.waitingOn ?? ""}`;
}

/** Entries from before the live ones, asked for as someone scrolls up. */
export interface SessionPage {
  /** Oldest first, ending just before the entry asked about. */
  entries: SessionEntry[];
  /** The session has more before these. */
  earlier: boolean;
}

/** How many earlier entries one scroll-up asks for. */
export const PAGE_SIZE = 200;

/** The most entries the view holds; anything older is left to the terminal. */
export const MAX_ENTRIES = 2000;

/**
 * What the view holds after a new live read: what it had, up to where the
 * live entries begin, then the live entries. The live read is the latest few
 * hundred, and slides forward as the agent works; entries that slide out stay.
 * When the live read no longer reaches back to anything held (the agent wrote
 * more than a whole read since the last one), what was held is let go.
 */
export function mergeLive(held: SessionEntry[], live: SessionEntry[]): SessionEntry[] {
  if (held.length === 0 || live.length === 0) return live;
  const first = live[0]._meta.id;
  const at = held.findIndex((e) => e._meta.id === first);
  if (at === -1) return live;
  return [...held.slice(0, at), ...live];
}

/** `page` put before `held`, with any entry both have kept once. */
export function prependPage(held: SessionEntry[], page: SessionEntry[]): SessionEntry[] {
  const ids = new Set(held.map((e) => e._meta.id));
  return [...page.filter((e) => !ids.has(e._meta.id)), ...held];
}

/** Asks the app for the entries before `before`. Never through the hub. */
export async function readEarlier(
  agent: { room: string; handle: string },
  before: string,
): Promise<SessionPage> {
  const invoke = appInvoke();
  if (!invoke) throw new Error("Not available to this page.");
  const page = (await invoke("agent_session_page", { ...agent, before, limit: PAGE_SIZE })) as SessionPage | null;
  return { entries: page?.entries ?? [], earlier: page?.earlier ?? false };
}

/** The text of a message's or thought's blocks. */
export const textOf = (blocks: TextBlock[]) => blocks.map((b) => b.text).join("\n\n");

/** A diff's changed lines, `+` added and `-` removed, with unchanged ones between, and its counts. */
export function diffLines(oldText: string | null, newText: string): { lines: string[]; added: number; removed: number } {
  const a = oldText ? oldText.split("\n") : [];
  const b = newText.split("\n");
  // The longest common run of lines, then a walk that emits the rest.
  const lcs = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  const lines: string[] = [];
  let added = 0;
  let removed = 0;
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      lines.push(`  ${a[i]}`);
      i++;
      j++;
    } else if (i < a.length && (j === b.length || lcs[i + 1][j] >= lcs[i][j + 1])) {
      // A removed line comes before what replaced it.
      lines.push(`- ${a[i++]}`);
      removed++;
    } else {
      lines.push(`+ ${b[j++]}`);
      added++;
    }
  }
  return { lines, added, removed };
}
