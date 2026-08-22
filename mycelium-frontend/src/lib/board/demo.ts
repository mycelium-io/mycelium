// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The demo layer: rows for the sources a live board would fill itself from —
 * herdr presence, CI, PRs — which this proof of concept has no reader for yet.
 *
 * Every row it makes is stamped `demo` and drawn dashed, so what the room
 * actually holds is never confused with what the surface is illustrating.
 */

import type { LiveItem } from "./item";
import { DAILY_GOAL, daysEnding, today, weekdayIndex, type ActivityEvent, type ActorKind } from "./activity";

const minutesAgo = (now: number, minutes: number): string =>
  new Date(now - minutes * 60000).toISOString();

export function demoItems(now: number): LiveItem[] {
  const rows: LiveItem[] = [
    {
      id: "demo:d3f",
      title: "JWT access-token TTL: 15m or 60m?",
      source: { kind: "episode", label: "@agent-y · episode d3f" },
      demo: true,
      fields: {
        status: "open",
        kind: "decision",
        owner: null,
        priority: "urgent",
        choices: ["15m", "60m"],
        asked_by: "@agent-y",
        updated: minutesAgo(now, 6),
        ttl_minutes: 120,
        thread: "episode d3f",
      },
    },
    {
      id: "demo:a91",
      title: "Enable thin-spoke join without a local replica",
      source: { kind: "github", label: "linked to #502" },
      demo: true,
      fields: {
        status: "blocked",
        kind: "blocked",
        owner: "@julia",
        priority: "high",
        blocked_by: ["#502"],
        issue: "#502",
        updated: minutesAgo(now, 40),
        ttl_minutes: null,
      },
    },
    {
      id: "demo:7c2",
      title: "@agent-z opened PR #504 and wants eyes on the custody seam",
      source: { kind: "github", label: "PR #504" },
      demo: true,
      fields: {
        status: "open",
        kind: "review",
        owner: "@agent-z",
        priority: "high",
        pr: "#504",
        ci: "green",
        branch: "feat/custody-seam",
        updated: minutesAgo(now, 12),
        ttl_minutes: 720,
      },
    },
    {
      id: "demo:b12",
      title: "Migrate auth → JWT",
      source: { kind: "agent", label: "@agent-y · claude_code" },
      demo: true,
      fields: {
        status: "in_progress",
        kind: "action",
        owner: "@agent-y",
        priority: "high",
        branch: "feat/jwt-auth",
        pr: "#502",
        ci: "green",
        live: true,
        blocks: ["Enable thin-spoke join"],
        updated: minutesAgo(now, 12),
        ttl_minutes: null,
      },
    },
    {
      id: "demo:e45",
      title: "Cache TTL sweep across the memory index",
      source: { kind: "agent", label: "@julia · human" },
      demo: true,
      fields: {
        status: "in_progress",
        kind: "action",
        owner: "@julia",
        priority: "normal",
        branch: "feat/cache",
        ci: "running",
        live: true,
        updated: minutesAgo(now, 3),
        ttl_minutes: null,
      },
    },
    {
      id: "demo:f88",
      title: "Aligner stalls when a proposer replies with prose only",
      source: { kind: "agent", label: "@agent-y · reported" },
      demo: true,
      fields: {
        status: "in_review",
        kind: "concern",
        owner: "@agent-y",
        priority: "normal",
        ci: "red",
        branch: "fix/offer-snap",
        updated: minutesAgo(now, 55),
        ttl_minutes: 1440,
      },
    },
    {
      id: "demo:c01",
      title: "Fix path traversal in the memory key encoder",
      source: { kind: "github", label: "PR #499 merged" },
      demo: true,
      fields: {
        status: "resolved",
        kind: "action",
        owner: "@agent-z",
        priority: "urgent",
        pr: "#499",
        ci: "green",
        updated: minutesAgo(now, 62),
        ttl_minutes: 1440,
      },
    },
    {
      id: "demo:c02",
      title: "Retire the SPIRE identity tier",
      source: { kind: "github", label: "promoted → #668" },
      demo: true,
      fields: {
        status: "resolved",
        kind: "concern",
        owner: "@julia",
        priority: "normal",
        issue: "#668",
        promoted: true,
        updated: minutesAgo(now, 200),
        ttl_minutes: 1440,
      },
    },
  ];
  return rows;
}

// ── Demo history ─────────────────────────────────────────────────────────────

/** Deterministic per-day pseudo-randomness: the same day always draws the same
 *  history, so the grid doesn't reshuffle itself on every render. */
function seeded(key: string): () => number {
  let h = 2166136261;
  for (let i = 0; i < key.length; i += 1) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return () => {
    h += 0x6d2b79f5;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const DEMO_ACTORS: { actor: string; actorKind: ActorKind; share: number }[] = [
  { actor: "agent-y", actorKind: "agent", share: 0.34 },
  { actor: "agent-z", actorKind: "agent", share: 0.28 },
  { actor: "julia", actorKind: "human", share: 0.24 },
  { actor: "aligner", actorKind: "engine", share: 0.14 },
];

const DEMO_WORK: { verb: string; titles: string[] }[] = [
  { verb: "resolved", titles: ["flip reads behind a flag", "retire the legacy store", "backfill parity check"] },
  { verb: "posted", titles: ["48h soak looks clean", "custody seam needs a second pass", "reads are behind the flag now"] },
  { verb: "wrote", titles: ["decisions/cutover", "status/sprint", "work/custody-notes"] },
  { verb: "converged", titles: ["cutover window · @growth @risk", "token ttl · @agent-y @julia"] },
  { verb: "completed", titles: ["dual-write to the new store", "rotate the signing key", "drain the old index"] },
];

/**
 * Ten weeks of plausible history, so the grid and the streaks have something to
 * show in a room that hasn't lived that long yet. Weekdays run busier than
 * weekends, and every event is stamped `demo` like the rest of the layer.
 */
export function demoActivity(now: number, tz: string): ActivityEvent[] {
  const end = today(tz, now);
  const events: ActivityEvent[] = [];

  const window = daysEnding(end, 70);
  for (const key of window) {
    const rand = seeded(key);
    const weekend = weekdayIndex(key) >= 5;
    const base = weekend ? rand() * 3 : 2 + rand() * 9;
    // Roughly one day in eight is quiet, the way a real one is.
    const drawn = Math.round(rand() > 0.88 ? 0 : base);
    // The last few days always carry something: the point of the demo layer is
    // to show what a lived-in log looks like, and a run that happens to end on
    // an empty today shows the opposite. Today lands short of the goal, because
    // a day you can still fill is the one worth looking at.
    const recent = window.length - window.indexOf(key) - 1;
    const count =
      recent === 0
        ? Math.max(3, Math.min(DAILY_GOAL - 2, drawn))
        : recent <= 2
          ? Math.max(2, drawn)
          : drawn;

    for (let i = 0; i < count; i += 1) {
      const roll = rand();
      let cumulative = 0;
      const who = DEMO_ACTORS.find(a => (cumulative += a.share) >= roll) ?? DEMO_ACTORS[0];
      const work = DEMO_WORK[Math.floor(rand() * DEMO_WORK.length)];
      const title = work.titles[Math.floor(rand() * work.titles.length)];
      const hour = 8 + Math.floor(rand() * 11);
      const minute = Math.floor(rand() * 60);
      events.push({
        id: `demo-act:${key}:${i}`,
        at: `${key}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00Z`,
        actor: who.actor,
        actorKind: who.actorKind,
        verb: work.verb,
        title,
        source: "demo layer",
        demo: true,
      });
    }
  }

  return events;
}
