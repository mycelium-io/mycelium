// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Project what the room already has into board rows.
 *
 * Nothing here is a new store: episodes, memories and presence are
 * read where they live and flattened into one row shape. The board is one filter on
 * the room, so a row can't be stale relative to the thing it describes, and
 * deleting the board would lose nothing.
 *
 * **One row per task.** A row and the thread its coordination happens in
 * are the same object, bound by the `episode` key the store puts on the row's
 * memory, so a task and its episode fold into one row rather than sitting beside
 * each other as two. The thread's state lands under `THREAD_FIELDS` and never on
 * the row's own axes: closing a negotiation inside a task must not resolve the
 * task or take it off whoever is holding it. An episode no row is bound to is an
 * **orphan** — it keeps a row of its own, because a recorded negotiation nobody
 * compiled into work is still something the room did.
 */

import type { AgentSummary, EpisodeSummary, Memory } from "@/lib/api";
import type { PresenceMember } from "@/lib/api";
import { ASSIGNMENT_FIELD, DEFAULT_TTL_MINUTES, ASSIGNABLE_NAMESPACES, assignmentOf } from "./assignment";
import type { LiveItem } from "./item";
import { memoryHref } from "@/lib/memory-routes";
import { memoryTitle } from "@/lib/memory-preview";

/** Namespaces whose memories read as coordination state rather than prose. */
const LIVE_NAMESPACES = ["decisions", "status", "work", "failed"];

/**
 * The store-owned frontmatter key binding a row to its thread. Minted by the
 * backend and carried across writes, so a row's thread is stable for its life.
 */
export const EPISODE_FIELD = "episode";

/**
 * What a row says about the thread inside it. Deliberately its own names: a
 * task's `status` and `assignment` are the task's, so a negotiation that converges
 * inside a row must not resolve the row or take it off its holder.
 */
export const THREAD_FIELDS = ["episode", "thread", "thread_state", "participants", "rounds"];

/**
 * How the thread inside a task reads. `open` while it is still running; the rest
 * are the commit subkinds a negotiation closes on.
 */
export const THREAD_STATES = ["open", "converged", "resolved", "rejected", "committed"];

/**
 * The row's own axes, which folding a thread onto it must never write. This is
 * the container-outlives-the-negotiation rule as a list.
 */
export const TASK_FIELDS = ["status", "assignment", "owner", "kind", "priority"];

/** Episode topics arrive as URNs; the board shows the part a person wrote. */
function prettyTopic(topic: string): string {
  const tail = topic.split(":").pop() ?? topic;
  return tail.replace(/[-_]+/g, " ");
}

function episodeItem(ep: EpisodeSummary, room: string): LiveItem {
  const subkind = ep.subkind ?? ep.outcome;
  const settled = subkind === "converged" || subkind === "resolved" || subkind === "rejected";
  const assignments = ep.assignments ?? {};
  const assignees = Object.keys(assignments);
  return {
    id: `episode:${ep.short_id}`,
    title: settled
      ? `${prettyTopic(ep.topic)}: ${subkind}`
      : `${prettyTopic(ep.topic)}: negotiating, ${ep.participants.length} at the table`,
    source: {
      kind: "episode",
      label: `episode ${ep.short_id}`,
      href: `/room/${encodeURIComponent(room)}?focus=episode:${encodeURIComponent(ep.short_id)}`,
    },
    fields: {
      [EPISODE_FIELD]: ep.episode,
      thread: ep.short_id,
      // A rejected negotiation reads open with kind=blocked, not a
      // "blocked" stage: it failed and wants a human.
      status: settled ? (subkind === "rejected" ? "open" : "resolved") : "in_review",
      kind: subkind === "rejected" ? "blocked" : "decision",
      owner: assignees.length === 1 ? `@${assignees[0]}` : null,
      priority: settled ? "normal" : "high",
      participants: ep.participants,
      rounds: ep.message_count,
      updated: ep.updated_at,
      ttl_minutes: settled ? 24 * 60 : null,
      // The room can answer a live negotiation from the row itself.
      choices: settled ? null : ep.participants.map(p => `side with @${p}`),
    },
  };
}

function memoryItem(memory: Memory, room: string): LiveItem {
  const namespace = memory.key.split("/")[0] ?? "";
  const value = memory.value;
  // Frontmatter beyond the store's own keys is the room's schema — it passes
  // straight through, which is what makes a custom namespace a typed view
  // without anyone configuring one.
  const custom: Record<string, unknown> =
    value && typeof value === "object" && !Array.isArray(value)
      ? { ...(value as Record<string, unknown>) }
      : {};
  delete custom.text;
  delete custom.content;

  const title = memoryTitle(memory);

  const derivedStatus = namespace === "decisions" ? "resolved" : "open";

  // A memory's own frontmatter, beyond the store's managed keys. This is where a
  // lease lands (`--meta owner=… claimed_at=…`), so a board that read only the
  // structured `value` would never see a claim anyone actually wrote.
  const meta: Record<string, unknown> =
    memory.meta && typeof memory.meta === "object" ? { ...memory.meta } : {};

  return {
    id: `memory:${memory.key}`,
    title: title || memory.key,
    source: {
      kind: "memory",
      label: memory.key,
      href: memoryHref(room, memory.key),
    },
    fields: {
      status: typeof custom.status === "string" ? custom.status : derivedStatus,
      kind: namespace === "decisions" ? "decision" : namespace === "failed" ? "blocked" : "concern",
      // Who wrote it last is provenance (`updated_by`), not assignment.
      // `owner` is written only by a claim; an unclaimed row says nobody.
      owner: null,
      writer: memory.updated_by ? `@${memory.updated_by}` : `@${memory.created_by}`,
      priority: "normal",
      namespace,
      tags: memory.tags ?? [],
      updated: memory.updated_at,
      ttl_minutes: null,
      // `work/` is the in-flight task, so it is the namespace that carries a
      // lease: frontmatter has somewhere to put a stamp, which is why leases
      // live here and not on plan tasks.
      ...(ASSIGNABLE_NAMESPACES.includes(namespace) ? { [ASSIGNMENT_FIELD]: "unclaimed" } : {}),
      ...custom,
      ...meta,
      // The binding is store-owned, so it arrives as its own field rather than
      // in the meta bag a caller can write.
      ...(memory.episode
        ? { [EPISODE_FIELD]: memory.episode, thread: memory.episode.split(":").pop() }
        : {}),
    },
  };
}

/**
 * What a task's row says about the thread inside it.
 *
 * Never the row's own axes (`TASK_FIELDS`) — a converged negotiation is a fact
 * about the conversation, not a claim that the work is done or that anyone is
 * holding it.
 */
function threadFields(ep: EpisodeSummary): Record<string, unknown> {
  return {
    thread_state: ep.subkind ?? ep.outcome ?? "open",
    participants: ep.participants,
    rounds: ep.message_count,
  };
}

/**
 * A resident agent is a peer, so it holds a row like anyone else. A merely
 * registered one doesn't: a board of things that need steering shouldn't carry a
 * line per manifest.
 */
function agentItem(agent: AgentSummary, presence: PresenceMember, now: string): LiveItem {
  // A SLIM member holds a live socket, so the hub sees it now; a server-held
  // member's lease is only as good as its last poll. Stamping both "now" made a
  // dead agent's row draw a full TTL bar forever — the row asserted a future its
  // holder had already stopped having.
  const lastSeen = presence.last_seen ?? now;
  return {
    id: `agent:${agent.handle}`,
    title: `@${agent.handle} is resident and awaiting work`,
    source: { kind: "agent", label: `${agent.adapter} · ${presence.kind}` },
    fields: {
      status: "open",
      kind: "signal",
      owner: `@${agent.handle}`,
      priority: "low",
      adapter: agent.adapter,
      live: true,
      updated: lastSeen,
      // Presence is a lease: the row drains unless the runtime keeps renewing it.
      [ASSIGNMENT_FIELD]: "held",
      claimed_at: lastSeen,
      ttl_minutes: DEFAULT_TTL_MINUTES,
    },
  };
}

export interface ProjectionInput {
  room: string;
  episodes: EpisodeSummary[];
  memories: Memory[];
  agents: AgentSummary[];
  presence: Map<string, PresenceMember>;
  now: string;
  /** Field writes applied locally until the server's copy catches up, keyed by item id. */
  optimisticEdits?: Record<string, Record<string, unknown>>;
  /** Rows captured in this session, before any backend write exists for them. */
  captured?: LiveItem[];
}

export function projectItems(input: ProjectionInput): LiveItem[] {
  const items: LiveItem[] = [];

  const rows = input.memories
    .filter(memory => LIVE_NAMESPACES.includes(memory.key.split("/")[0] ?? ""))
    .map(memory => memoryItem(memory, input.room));
  // A task folds in its thread; what nothing folded is an orphan episode, which
  // keeps its own row rather than being hidden.
  const byUrn = new Map(input.episodes.map(ep => [ep.episode, ep]));
  const folded = new Set<string>();
  for (const row of rows) {
    const ep = byUrn.get(row.fields[EPISODE_FIELD] as string);
    if (!ep) continue;
    folded.add(ep.episode);
    Object.assign(row.fields, threadFields(ep));
  }
  for (const ep of input.episodes) {
    if (!folded.has(ep.episode)) items.push(episodeItem(ep, input.room));
  }
  items.push(...rows);
  // Nor does an agent whose lease has drained — a session that went quiet an
  // hour ago is not residency, and a row saying it is would be the board's most
  // expensive lie.
  const clock = Date.parse(input.now) || Date.now();
  for (const agent of input.agents) {
    const presence = input.presence.get(agent.handle.toLowerCase());
    if (!presence) continue;
    const row = agentItem(agent, presence, input.now);
    if (assignmentOf(row, clock) === "held") items.push(row);
  }
  items.push(...(input.captured ?? []));

  const edits = input.optimisticEdits ?? {};
  return items.map(item =>
    edits[item.id] ? { ...item, fields: { ...item.fields, ...edits[item.id] } } : item,
  );
}
