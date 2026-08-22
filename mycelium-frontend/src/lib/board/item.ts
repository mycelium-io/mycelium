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

export type SourceKind = "plan" | "episode" | "memory" | "agent" | "capture" | "github";

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
  /** Synthetic row from the demo layer, never mistaken for room state. */
  demo?: boolean;
}

/** The three lenses. "Needs you" is the default; the firehose is opt-in. */
export type Lens = "needs_you" | "in_flight" | "resolved";

export const LENSES: { id: Lens; label: string; blurb: string }[] = [
  { id: "needs_you", label: "Needs you", blurb: "waiting on a human steer" },
  { id: "in_flight", label: "In flight", blurb: "claimed and moving" },
  { id: "resolved", label: "Resolved", blurb: "done today, auto-hides" },
];

export type ItemStatus =
  | "open"
  | "claimed"
  | "in_progress"
  | "in_review"
  | "blocked"
  | "resolved"
  | "dismissed";

export type ItemKind = "decision" | "blocked" | "review" | "action" | "concern" | "signal";

export type Priority = "urgent" | "high" | "normal" | "low";

export const STATUS_ORDER: ItemStatus[] = [
  "open",
  "claimed",
  "in_progress",
  "in_review",
  "blocked",
  "resolved",
  "dismissed",
];

export const PRIORITY_ORDER: Priority[] = ["urgent", "high", "normal", "low"];

// ── Field access ─────────────────────────────────────────────────────────────
// Fields are untyped on purpose: a room can put anything in frontmatter, and a
// row missing a field the cockpit likes still renders rather than crashing.

export function str(item: LiveItem, name: string): string | null {
  const v = item.fields[name];
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

export function num(item: LiveItem, name: string): number | null {
  const v = item.fields[name];
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() && Number.isFinite(Number(v))) return Number(v);
  return null;
}

export function arr(item: LiveItem, name: string): string[] {
  const v = item.fields[name];
  if (Array.isArray(v)) return v.filter((x): x is string => typeof x === "string");
  if (typeof v === "string" && v.trim()) return [v.trim()];
  return [];
}

export function bool(item: LiveItem, name: string): boolean {
  return item.fields[name] === true;
}

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

export function ownerOf(item: LiveItem): string | null {
  const o = str(item, "owner");
  return o ? o.replace(/^@/, "") : null;
}

/**
 * The lens is derived, never stored: a row can't drift out of sync with the
 * board it belongs on, and re-lensing is a consequence of a state change rather
 * than a second write.
 */
export function lensOf(item: LiveItem): Lens {
  const status = statusOf(item);
  if (status === "resolved" || status === "dismissed") return "resolved";
  if (status === "open" || status === "blocked") return "needs_you";
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

/** Fraction of the row's TTL already spent, or null when it doesn't expire. */
export function ttlSpent(item: LiveItem, now: number): number | null {
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

export type Verb = "claim" | "resolve" | "block" | "unblock" | "promote" | "dismiss";

export const VERBS: { id: Verb; key: string; label: string }[] = [
  { id: "claim", key: "c", label: "Claim" },
  { id: "resolve", key: "r", label: "Resolve" },
  { id: "block", key: "b", label: "Block" },
  { id: "promote", key: "p", label: "Promote → GH" },
  { id: "dismiss", key: "x", label: "Dismiss" },
];

export interface VerbContext {
  /** Who the gesture acts as — `claim` with no target claims for you. */
  actor: string;
  now: string;
  /** Issue number a `promote` would file as, in a PoC with no GitHub write. */
  issueNumber?: number;
}

/**
 * A verb returns the field patch it implies. `promote` is the one that leaves
 * the board: it stamps the back-link and resolves, because the record now lives
 * in GitHub and the live slice shouldn't hold a second copy of it.
 */
export function applyVerb(
  item: LiveItem,
  verb: Verb,
  ctx: VerbContext,
): Record<string, unknown> {
  const patch: Record<string, unknown> = { updated: ctx.now };
  switch (verb) {
    case "claim":
      patch.status = "in_progress";
      patch.owner = ownerOf(item) ?? ctx.actor;
      break;
    case "resolve":
      patch.status = "resolved";
      break;
    case "block":
      patch.status = "blocked";
      break;
    case "unblock":
      patch.status = ownerOf(item) ? "in_progress" : "open";
      break;
    case "promote":
      patch.status = "resolved";
      patch.promoted = true;
      if (ctx.issueNumber) patch.issue = `#${ctx.issueNumber}`;
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
