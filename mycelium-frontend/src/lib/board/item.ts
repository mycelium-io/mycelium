// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The board's row primitive.
 *
 * A row is a stable identity plus a bag of frontmatter `fields`. Everything the
 * surface does — the "needs you" cockpit, the kanban, the table — is a
 * projection over that bag, so the coordination surface and a typed view over a
 * namespace are one mechanism rather than two features.
 */

import {
  BLOCKED_FIELD,
  LENS_OF_CUSTODY,
  claimPatch,
  custodyOf,
  isBlocked,
  leaseSpent,
  releasePatch,
} from "./custody";
import { arr, bool, num, ownerOf, str } from "./fields";

// The accessors live a layer down so `custody` can read a row without importing
// this module back; callers still find them here, where they always were.
export { arr, bool, num, ownerOf, str };

export type SourceKind = "episode" | "memory" | "agent" | "github";

export interface ItemSource {
  kind: SourceKind;
  /** What produced this row, in the room's own terms ("plan/tasks.md"). */
  label: string;
  /** Where the row came from, when the thing behind it is openable. */
  href?: string;
}

export interface LiveItem {
  id: string;
  title: string;
  source: ItemSource;
  /** The frontmatter. Typed views project over exactly this and nothing else. */
  fields: Record<string, unknown>;
}

/** The three lenses. "Needs you" is the default; the firehose is opt-in. */
export type Lens = "needs_you" | "in_flight" | "resolved";

export const LENSES: { id: Lens; label: string; blurb: string }[] = [
  { id: "needs_you", label: "Needs you", blurb: "waiting on a human steer" },
  { id: "in_flight", label: "In flight", blurb: "claimed and moving" },
  { id: "resolved", label: "Resolved", blurb: "done today, auto-hides" },
];

/**
 * The stage a row is at, and only that. Who holds it is `custody` (a lease that
 * drains); whether it is blocked is derived from `blocked_by`. Both used to be
 * spelled here, which is how one field ended up doing three jobs.
 */
export type ItemStatus = "open" | "in_review" | "resolved" | "dismissed";

export type ItemKind = "decision" | "blocked" | "review" | "action" | "concern" | "signal";

export type Priority = "urgent" | "high" | "normal" | "low";

export const STATUS_ORDER: ItemStatus[] = ["open", "in_review", "resolved", "dismissed"];

export const PRIORITY_ORDER: Priority[] = ["urgent", "high", "normal", "low"];

export function statusOf(item: LiveItem): ItemStatus {
  const s = str(item, "status");
  return (STATUS_ORDER as string[]).includes(s ?? "") ? (s as ItemStatus) : "open";
}

export function kindOf(item: LiveItem): ItemKind {
  const k = str(item, "kind");
  const known: string[] = ["decision", "blocked", "review", "action", "concern", "signal"];
  return known.includes(k ?? "") ? (k as ItemKind) : "action";
}

export function priorityOf(item: LiveItem): Priority {
  const p = str(item, "priority");
  return (PRIORITY_ORDER as string[]).includes(p ?? "") ? (p as Priority) : "normal";
}

/**
 * The lens is derived, never stored: a row can't drift out of sync with the
 * board it belongs on, and re-lensing is a consequence of a state change rather
 * than a second write.
 *
 * Custody first, stage only where there is none — a row someone holds belongs on
 * the board by who holds it, and one whose holder went quiet drains back to the
 * pool without anyone touching it. Blocked beats both: a row waiting on
 * something needs a person whoever is nominally on it.
 *
 * `now` defaults to the wall clock so a caller with no shared tick still reads
 * a live board; the board's own surfaces pass their tick, which is what keeps a
 * render and its test deterministic.
 */
export function lensOf(item: LiveItem, now: number = Date.now()): Lens {
  if (isBlocked(item)) return "needs_you";
  const custody = custodyOf(item, now);
  if (custody) return LENS_OF_CUSTODY[custody];
  const status = statusOf(item);
  if (status === "resolved" || status === "dismissed") return "resolved";
  if (status === "open") return "needs_you";
  return "in_flight";
}

/** Minutes since the row last moved, for the age column and the TTL bar. */
export function ageMinutes(item: LiveItem, now: number): number | null {
  const raw = str(item, "updated") ?? str(item, "created");
  if (!raw) return null;
  const t = Date.parse(raw);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.round((now - t) / 60000));
}

/**
 * Fraction of the row's TTL already spent, or null when it doesn't expire.
 *
 * A lease ages from `claimed_at` rather than from `updated`: a renewal re-dates
 * the claim, and a holder saying "still here" is exactly what the bar is drawing.
 */
export function ttlSpent(item: LiveItem, now: number): number | null {
  const lease = leaseSpent(item, now);
  if (lease !== null) return Math.min(1, lease);
  const ttl = num(item, "ttl_minutes");
  const age = ageMinutes(item, now);
  if (ttl === null || ttl <= 0 || age === null) return null;
  return Math.min(1, age / ttl);
}

export function formatAge(minutes: number | null): string {
  if (minutes === null) return "-";
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

// ── Triage verbs ─────────────────────────────────────────────────────────────
// The same verbs an agent drives over the ledger. Each is a pure field patch,
// so a keystroke here and an agent's call over L9 are the same state change.

export type Verb =
  | "claim"
  | "release"
  | "resolve"
  | "block"
  | "unblock"
  | "promote"
  | "dismiss";

export const VERBS: { id: Verb; key: string; label: string }[] = [
  { id: "claim", key: "c", label: "Claim" },
  { id: "release", key: "e", label: "Release" },
  { id: "resolve", key: "r", label: "Resolve" },
  { id: "block", key: "b", label: "Block" },
  { id: "promote", key: "p", label: "Promote → GH" },
  { id: "dismiss", key: "x", label: "Dismiss" },
];

export interface VerbContext {
  /** Who the gesture acts as — `claim` with no target claims for you. */
  actor: string;
  now: string;
  /** Why a `release` is handing the row back, recorded against the releaser. */
  note?: string;
  /** Minutes a `claim` holds for before it drains. */
  ttlMinutes?: number;
  /** What a `block` is waiting on: the only thing that makes a row blocked. */
  blockedBy?: string;
}

/**
 * A verb returns the field patch it implies. `promote` is the one that leaves
 * the board: it marks the row as belonging somewhere more durable and resolves,
 * so the live slice stops carrying it. It does not stamp a back-link — nothing
 * here files the issue, and a reference the verb invented would be one the
 * status providers then resolve against a real, unrelated one.
 */
export function applyVerb(
  item: LiveItem,
  verb: Verb,
  ctx: VerbContext,
): Record<string, unknown> {
  const patch: Record<string, unknown> = { updated: ctx.now };
  switch (verb) {
    case "claim":
      // A claim is a lease, not a stage: it says who holds the row and until
      // when, and it says nothing about how far along the work is.
      Object.assign(patch, claimPatch(ownerOf(item) ?? ctx.actor, ctx.now, ctx.ttlMinutes));
      break;
    case "release":
      Object.assign(patch, releasePatch(ctx.actor, ctx.now, ctx.note));
      break;
    case "resolve":
      patch.status = "resolved";
      if (custodyOf(item, Date.parse(ctx.now)) !== null) patch.custody = "resolved";
      break;
    case "block":
      // Nothing writes the word "blocked": a row is blocked because it names a
      // blocker, and the renderer has read `blocked_by` all along.
      patch[BLOCKED_FIELD] = ctx.blockedBy ?? "unspecified";
      break;
    case "unblock":
      patch[BLOCKED_FIELD] = null;
      break;
    case "promote":
      patch.status = "resolved";
      patch.promoted = true;
      break;
    case "dismiss":
      patch.status = "dismissed";
      break;
  }
  return patch;
}

export function mergeItem(item: LiveItem, patch: Record<string, unknown>): LiveItem {
  return { ...item, fields: { ...item.fields, ...patch } };
}
