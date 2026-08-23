// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The room's day, and the days behind it.
 *
 * The board answers "what needs me". This answers "what did we do" — the same
 * room state, bucketed by calendar day in the reader's own timezone and
 * attributed to whoever moved it. Agents and people are the same kind of row
 * here, because on a shared board they are the same kind of worker.
 *
 * A day is a *calendar* day, which is why the timezone matters: an agent
 * finishing at 23:40 in Dublin and a person starting at 08:00 in Denver are
 * only on the same day if you say which clock you meant.
 */

import type { EpisodeSummary, Memory, RoomMessage } from "@/lib/api";
import { memoryHref } from "@/lib/memory-routes";
import { parseJsonRawText } from "@/lib/json-text";

export type ActorKind = "agent" | "engine" | "human";

export interface ActivityEvent {
  id: string;
  /** ISO instant. The day it lands on depends on the zone you read it in. */
  at: string;
  actor: string;
  actorKind: ActorKind;
  /** Past tense, one word where possible: posted, wrote, resolved, converged. */
  verb: string;
  title: string;
  source: string;
  href?: string;
}

/** `YYYY-MM-DD`, as read in `tz`. */
export type DayKey = string;

export interface Day {
  key: DayKey;
  events: ActivityEvent[];
}

/** Engines are first-party cognition; naming them apart keeps the lanes honest. */
const ENGINES = new Set(["aligner", "synthesizer"]);

export function actorKind(handle: string, agents: Set<string>): ActorKind {
  const clean = handle.replace(/^@/, "").toLowerCase();
  if (ENGINES.has(clean)) return "engine";
  return agents.has(clean) ? "agent" : "human";
}

// ── Calendar ─────────────────────────────────────────────────────────────────

/**
 * The day an instant falls on, in `tz`. `en-CA` because it formats as
 * `YYYY-MM-DD`, which sorts and compares as a string.
 */
export function dayKey(iso: string, tz: string): DayKey | null {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: tz,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date(t));
  } catch {
    // An unknown zone shouldn't blank the view; fall back to the host's.
    return new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit" }).format(
      new Date(t),
    );
  }
}

/**
 * Calendar arithmetic on the key itself rather than on an instant: adding a day
 * to `2026-10-25` is a date operation, and doing it in milliseconds lands an
 * hour out on the days a zone changes offset.
 */
export function shiftDay(key: DayKey, days: number): DayKey {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

export function today(tz: string, now: number = Date.now()): DayKey {
  return dayKey(new Date(now).toISOString(), tz) ?? new Date(now).toISOString().slice(0, 10);
}

/** `count` day keys ending at `end`, oldest first. */
export function daysEnding(end: DayKey, count: number): DayKey[] {
  return Array.from({ length: count }, (_, i) => shiftDay(end, i - count + 1));
}

/** 0 = Monday. Weeks start Monday, so a grid column is a working week. */
export function weekdayIndex(key: DayKey): number {
  const [y, m, d] = key.split("-").map(Number);
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

export function formatDay(key: DayKey, opts: Intl.DateTimeFormatOptions = {}): string {
  const [y, m, d] = key.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, {
    timeZone: "UTC",
    weekday: "long",
    day: "numeric",
    month: "long",
    ...opts,
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

export function formatTime(iso: string, tz: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: tz,
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return "";
  }
}

/** Zones offered in the picker, plus whatever the browser is actually set to. */
export const COMMON_ZONES = [
  "UTC",
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Dublin",
  "Europe/Berlin",
  "Europe/Warsaw",
  "Africa/Lagos",
  "Asia/Jerusalem",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

export function localZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

// ── Projection ───────────────────────────────────────────────────────────────

export interface ActivityInput {
  room: string;
  messages: RoomMessage[];
  memories: Memory[];
  episodes: EpisodeSummary[];
  agentHandles: string[];
}

/**
 * Flatten every timestamped fact the room can tell us into one attributed
 * stream. Nothing is invented: if a source doesn't record who or when, it
 * doesn't produce an event.
 */
export function projectActivity(input: ActivityInput): ActivityEvent[] {
  const agents = new Set(input.agentHandles.map(h => h.toLowerCase()));
  const events: ActivityEvent[] = [];
  const push = (event: ActivityEvent | null) => {
    if (event && Date.parse(event.at)) events.push(event);
  };

  for (const [i, message] of input.messages.entries()) {
    const actor = (message.sender_handle ?? "").replace(/^@/, "");
    const type = (message.message_type ?? message.type ?? "") as string;
    if (!actor || !message.created_at || SKIP_TYPES.has(type)) continue;
    const said = describe(type, message.content);
    if (!said) continue;
    push({
      id: `msg:${message.id ?? i}`,
      at: message.created_at,
      actor,
      actorKind: actorKind(actor, agents),
      verb: said.verb,
      title: said.title,
      source: "channel",
    });
  }

  for (const memory of input.memories) {
    const actor = (memory.updated_by ?? memory.created_by ?? "").replace(/^@/, "");
    if (!actor || !memory.updated_at) continue;
    push({
      id: `mem:${memory.key}:${memory.version}`,
      at: memory.updated_at,
      actor,
      actorKind: actorKind(actor, agents),
      verb: memory.version > 1 ? "revised" : "wrote",
      title: memory.key,
      source: `memory · v${memory.version}`,
      href: memoryHref(input.room, memory.key),
    });
  }

  for (const episode of input.episodes) {
    const subkind = episode.subkind ?? episode.outcome;
    push({
      id: `ep:${episode.short_id}`,
      at: episode.updated_at,
      actor: episode.updated_by || "aligner",
      actorKind: "engine",
      verb: subkind === "converged" || subkind === "resolved" ? "converged" : "mediated",
      title: `${episode.topic.split(":").pop()} · ${episode.participants.map(p => `@${p}`).join(" ")}`,
      source: `episode ${episode.short_id}`,
    });
  }

  return events.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}

// ── Buckets, streaks, heat ───────────────────────────────────────────────────

export function byDay(events: ActivityEvent[], tz: string): Map<DayKey, ActivityEvent[]> {
  const days = new Map<DayKey, ActivityEvent[]>();
  for (const event of events) {
    const key = dayKey(event.at, tz);
    if (!key) continue;
    if (!days.has(key)) days.set(key, []);
    days.get(key)!.push(event);
  }
  return days;
}

export interface ActorDay {
  actor: string;
  actorKind: ActorKind;
  events: ActivityEvent[];
}

/** One lane per actor, busiest first — attribution, not a leaderboard. */
export function byActor(events: ActivityEvent[]): ActorDay[] {
  const lanes = new Map<string, ActorDay>();
  for (const event of events) {
    const key = event.actor.toLowerCase();
    if (!lanes.has(key)) {
      lanes.set(key, { actor: event.actor, actorKind: event.actorKind, events: [] });
    }
    lanes.get(key)!.events.push(event);
  }
  return [...lanes.values()].sort(
    (a, b) => b.events.length - a.events.length || a.actor.localeCompare(b.actor),
  );
}

/** Five steps, because a heat grid people can read has about five. */
export function heatLevel(count: number): 0 | 1 | 2 | 3 | 4 {
  if (count === 0) return 0;
  if (count <= 2) return 1;
  if (count <= 5) return 2;
  if (count <= 9) return 3;
  return 4;
}

export interface Streaks {
  current: number;
  longest: number;
}

/**
 * A streak of days with any activity. Today not having started yet shouldn't
 * break yesterday's run, so a current streak may end on either.
 */
export function streaks(days: Map<DayKey, ActivityEvent[]>, end: DayKey): Streaks {
  const active = (key: DayKey) => (days.get(key)?.length ?? 0) > 0;

  let current = 0;
  let cursor = active(end) ? end : shiftDay(end, -1);
  while (active(cursor)) {
    current += 1;
    cursor = shiftDay(cursor, -1);
  }

  const keys = [...days.keys()].filter(k => (days.get(k)?.length ?? 0) > 0).sort();
  let longest = 0;
  let run = 0;
  let previous: DayKey | null = null;
  for (const key of keys) {
    run = previous && shiftDay(previous, 1) === key ? run + 1 : 1;
    longest = Math.max(longest, run);
    previous = key;
  }

  return { current, longest };
}

/** What a range of days adds up to: the "what did we work on" answer. */
export interface Digest {
  from: DayKey;
  to: DayKey;
  events: ActivityEvent[];
  actors: ActorDay[];
  activeDays: number;
  byVerb: { verb: string; count: number }[];
}

export function digest(days: Map<DayKey, ActivityEvent[]>, from: DayKey, to: DayKey): Digest {
  const events: ActivityEvent[] = [];
  let activeDays = 0;
  for (let key = from; key <= to; key = shiftDay(key, 1)) {
    const forDay = days.get(key) ?? [];
    if (forDay.length) activeDays += 1;
    events.push(...forDay);
  }
  const verbs = new Map<string, number>();
  for (const event of events) verbs.set(event.verb, (verbs.get(event.verb) ?? 0) + 1);
  return {
    from,
    to,
    events: events.sort((a, b) => Date.parse(b.at) - Date.parse(a.at)),
    actors: byActor(events),
    activeDays,
    byVerb: [...verbs.entries()]
      .map(([verb, count]) => ({ verb, count }))
      .sort((a, b) => b.count - a.count),
  };
}

/** How full today's log is. A target to fill, not a quota anyone is held to. */
export const DAILY_GOAL = 6;

const CHAT_TYPES = new Set(["broadcast", "direct", "announce", "delegate"]);

/**
 * Facts the log reads from a truer source than the wire.
 *
 * A memory write and a plan edit are already counted from the store itself, and
 * a consensus is counted from its episode — re-counting the message announcing
 * each would log the same work twice.
 */
const SKIP_TYPES = new Set([
  "memory_changed",
  "coordination_consensus",
  "consent_request",
  "presence",
]);

/**
 * What a message says, in the log's terms. Coordination payloads are JSON on
 * the wire, so they're read by type rather than printed — a log line is who did
 * what, not the envelope they did it in.
 */
function describe(type: string, content: unknown): { verb: string; title: string } | null {
  if (CHAT_TYPES.has(type)) {
    const text = typeof content === "string" ? content : "";
    return { verb: "posted", title: firstLine(text) || "a message" };
  }
  if (!type.startsWith("coordination_")) return null;

  const raw =
    typeof content === "string"
      ? ((parseJsonRawText(content) as Record<string, unknown> | null) ?? {})
      : ((content as Record<string, unknown>) ?? {});

  if (type === "coordination_tick") {
    const tick = (raw.payload as Record<string, unknown>) ?? raw;
    const round = tick.round ?? "?";
    const who = tick.participant_id ? `@${tick.participant_id}` : "a participant";
    return { verb: "negotiated", title: `round ${round} · ${who} ${tick.action ?? "replied"}` };
  }
  if (type === "coordination_join") {
    return { verb: "joined", title: String(raw.intent ?? "the episode") };
  }
  if (type === "coordination_start") {
    return { verb: "opened", title: `an episode with ${raw.agent_count ?? "?"} agents` };
  }
  return { verb: type.replace("coordination_", ""), title: "" };
}

function firstLine(text: string): string {
  const line = text.split("\n").map(l => l.trim()).find(Boolean) ?? "";
  return line.replace(/^#+\s*/, "").slice(0, 110);
}
