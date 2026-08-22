// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Project what the room already has into board rows.
 *
 * Nothing here is a new store: plan tasks, episodes, memories and presence are
 * read where they live and flattened into one row shape. The board is a lens on
 * the room, so a row can't be stale relative to the thing it describes, and
 * deleting the board would lose nothing.
 */

import type { AgentSummary, EpisodeSummary, Memory, PlanResponse, PlanTask } from "@/lib/api";
import type { PresenceMember } from "@/lib/api";
import type { LiveItem } from "./item";
import { memoryHref } from "@/lib/memory-routes";

/** Namespaces whose memories read as coordination state rather than prose. */
const LIVE_NAMESPACES = ["decisions", "status", "work", "failed"];

/** `@handle` anywhere in a task line is its owner — how the compiler writes them. */
const OWNER_RE = /@([a-z0-9][a-z0-9._-]*)/i;
/** `#123` in a line points at the GitHub record behind the work. */
const ISSUE_RE = /#(\d+)/;

function priorityFromText(text: string): string {
  const t = text.toLowerCase();
  if (/\b(urgent|asap|blocker|critical)\b/.test(t)) return "urgent";
  if (/\b(important|high|soon)\b/.test(t)) return "high";
  if (/\b(nit|minor|someday|nice to have)\b/.test(t)) return "low";
  return "normal";
}

function stripMarkup(text: string): string {
  return text.replace(OWNER_RE, "").replace(/\s{2,}/g, " ").trim();
}

function planItem(task: PlanTask, plan: PlanResponse, now: string): LiveItem {
  const owner = task.text.match(OWNER_RE)?.[1] ?? null;
  const issue = task.text.match(ISSUE_RE)?.[0] ?? null;
  const file = plan.files.find(f => f.slug === task.slug);
  return {
    id: `plan:${task.id}`,
    title: stripMarkup(task.text) || task.text,
    source: {
      kind: "plan",
      label: `plan/${task.slug}.md:${task.line}`,
    },
    fields: {
      status: task.done ? "resolved" : owner ? "in_progress" : "open",
      kind: "action",
      owner: owner ? `@${owner}` : null,
      priority: priorityFromText(task.text),
      issue,
      updated: file?.updated_at ?? now,
      // A compiled plan task is the room's durable commitment, so it is the one
      // row kind with no TTL — it leaves by being done, not by expiring.
      ttl_minutes: null,
    },
  };
}

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
      status: settled ? (subkind === "rejected" ? "blocked" : "resolved") : "in_review",
      kind: "decision",
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

  const title =
    typeof custom.title === "string"
      ? custom.title
      : typeof value === "string"
        ? firstLine(value)
        : firstLine(memory.content_text ?? memory.key);

  const derivedStatus =
    namespace === "failed" ? "blocked" : namespace === "decisions" ? "resolved" : "open";

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
      owner: memory.updated_by ? `@${memory.updated_by}` : `@${memory.created_by}`,
      priority: "normal",
      namespace,
      tags: memory.tags ?? [],
      updated: memory.updated_at,
      ttl_minutes: null,
      ...custom,
    },
  };
}

/**
 * A resident agent is a peer, so it holds a row like anyone else. A merely
 * registered one doesn't: a board of things that need steering shouldn't carry a
 * line per manifest.
 */
function agentItem(agent: AgentSummary, presence: PresenceMember, now: string): LiveItem {
  return {
    id: `agent:${agent.handle}`,
    title: `@${agent.handle} is resident and awaiting work`,
    source: { kind: "agent", label: `${agent.adapter} · ${presence.kind}` },
    fields: {
      status: "claimed",
      kind: "signal",
      owner: `@${agent.handle}`,
      priority: "low",
      adapter: agent.adapter,
      live: true,
      updated: now,
      // Presence is a lease: the row drains unless the runtime keeps renewing it.
      ttl_minutes: 30,
    },
  };
}

function firstLine(text: string): string {
  const line = text.split("\n").map(l => l.trim()).find(l => l && !l.startsWith("---"));
  return (line ?? "").replace(/^#+\s*/, "").slice(0, 120);
}

export interface ProjectionInput {
  room: string;
  plan: PlanResponse | null;
  episodes: EpisodeSummary[];
  memories: Memory[];
  agents: AgentSummary[];
  presence: Map<string, PresenceMember>;
  now: string;
  /** Rows an agent hasn't touched yet: local triage, keyed by item id. */
  overlay?: Record<string, Record<string, unknown>>;
  /** Rows captured in this session, before any backend write exists for them. */
  captured?: LiveItem[];
  /** Synthetic rows, shown only while the demo layer is on. */
  demo?: LiveItem[];
}

export function projectItems(input: ProjectionInput): LiveItem[] {
  const items: LiveItem[] = [];

  for (const task of input.plan?.tasks ?? []) items.push(planItem(task, input.plan!, input.now));
  for (const ep of input.episodes) items.push(episodeItem(ep, input.room));
  for (const memory of input.memories) {
    if (!LIVE_NAMESPACES.includes(memory.key.split("/")[0] ?? "")) continue;
    items.push(memoryItem(memory, input.room));
  }
  for (const agent of input.agents) {
    const presence = input.presence.get(agent.handle.toLowerCase());
    if (presence) items.push(agentItem(agent, presence, input.now));
  }
  items.push(...(input.captured ?? []));
  items.push(...(input.demo ?? []));

  const overlay = input.overlay ?? {};
  return items.map(item =>
    overlay[item.id] ? { ...item, fields: { ...item.fields, ...overlay[item.id] } } : item,
  );
}
