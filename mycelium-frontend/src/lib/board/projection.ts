// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Project what the room already has into board rows.
 *
 * Nothing here is a new store: episodes, memories and presence are
 * read where they live and flattened into one row shape. The board is a lens on
 * the room, so a row can't be stale relative to the thing it describes, and
 * deleting the board would lose nothing.
 */

import type { AgentSummary, EpisodeSummary, Memory } from "@/lib/api";
import type { PresenceMember } from "@/lib/api";
import { CUSTODY_FIELD, DEFAULT_TTL_MINUTES, LEASABLE_NAMESPACES, custodyOf } from "./custody";
import type { LiveItem } from "./item";
import { memoryHref } from "@/lib/memory-routes";

/** Namespaces whose memories read as coordination state rather than prose. */
const LIVE_NAMESPACES = ["decisions", "status", "work", "failed"];

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
      // A rejected negotiation is not a stage called "blocked" — nothing is
      // blocking it, it failed and wants a human. It reads open, and the kind
      // carries what happened.
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

  const title =
    typeof custom.title === "string"
      ? custom.title
      : typeof value === "string"
        ? firstLine(value)
        : firstLine(memory.content_text ?? memory.key);

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
      // Only a namespace that genuinely implies a kind sets one. Everything
      // else leaves it to `kindOf`, which has the single fallback — writing
      // "concern" here made it mean two things at once: a worry somebody
      // flagged, and "we don't know what this is".
      ...(namespace === "decisions"
        ? { kind: "decision" }
        : namespace === "failed"
          ? { kind: "blocked" }
          : {}),
      // Who wrote it last is provenance, not custody. Reading `owner` off
      // `updated_by` gave every memory in the room a holder, which is the
      // confident-lie failure this axis exists to stop: a holder is something a
      // claim writes, so an unclaimed row says nobody.
      owner: null,
      writer: memory.updated_by ? `@${memory.updated_by}` : `@${memory.created_by}`,
      priority: "normal",
      namespace,
      tags: memory.tags ?? [],
      updated: memory.updated_at,
      ttl_minutes: null,
      // `work/` is the in-flight unit, so it is the namespace that carries a
      // lease: frontmatter has somewhere to put a stamp, which is why leases
      // live here and not on plan tasks.
      ...(LEASABLE_NAMESPACES.includes(namespace) ? { [CUSTODY_FIELD]: "unclaimed" } : {}),
      ...custom,
      ...meta,
    },
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
      [CUSTODY_FIELD]: "held",
      claimed_at: lastSeen,
      ttl_minutes: DEFAULT_TTL_MINUTES,
    },
  };
}

function firstLine(text: string): string {
  const line = text.split("\n").map(l => l.trim()).find(l => l && !l.startsWith("---"));
  return (line ?? "").replace(/^#+\s*/, "").slice(0, 120);
}

export interface ProjectionInput {
  room: string;
  episodes: EpisodeSummary[];
  memories: Memory[];
  agents: AgentSummary[];
  presence: Map<string, PresenceMember>;
  now: string;
  /** Optimistic values for writes still in flight, keyed by item id. Cleared
   *  the moment the write settles, so this can never outlast the request. */
  overlay?: Record<string, Record<string, unknown>>;
}

export function projectItems(input: ProjectionInput): LiveItem[] {
  const items: LiveItem[] = [];

  for (const ep of input.episodes) items.push(episodeItem(ep, input.room));
  for (const memory of input.memories) {
    if (!LIVE_NAMESPACES.includes(memory.key.split("/")[0] ?? "")) continue;
    items.push(memoryItem(memory, input.room));
  }
  // Nor does an agent whose lease has drained — a session that went quiet an
  // hour ago is not residency, and a row saying it is would be the board's most
  // expensive lie.
  const clock = Date.parse(input.now) || Date.now();
  for (const agent of input.agents) {
    const presence = input.presence.get(agent.handle.toLowerCase());
    if (!presence) continue;
    const row = agentItem(agent, presence, input.now);
    if (custodyOf(row, clock) === "held") items.push(row);
  }

  const overlay = input.overlay ?? {};
  return items.map(item =>
    overlay[item.id] ? { ...item, fields: { ...item.fields, ...overlay[item.id] } } : item,
  );
}
