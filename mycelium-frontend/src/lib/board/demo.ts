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
