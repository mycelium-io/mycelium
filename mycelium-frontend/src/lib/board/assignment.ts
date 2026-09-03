// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Assignment: who holds a row, and for how much longer.
 *
 * An agent is resident rather than one-shot, but no session gets to announce
 * that it ended — a container is reclaimed, a cloud session times out, a job is
 * canceled. So every assertion an ephemeral actor makes about the future is a
 * lease, because none of them can promise the future.
 *
 * Held as a fact, one dead agent leaves the board asserting "@someone is on
 * this" forever, and the board degrades exactly as it gets busy: full of
 * confident lies. Held as a lease, an abandoned claim drains and the row returns
 * to the pool.
 *
 * **Assignment is not a stage.** `status` is a stage vocabulary, borrowed from
 * tools built for workers who do not die silently. `in_review` says nothing
 * about whether anyone is alive; `held, renewed 30s ago` says everything.
 *
 * **It is the freshness model the upstream half already ships.** A cached
 * provider answer is fresh / stale / missing against `fetched_at` + a TTL; a
 * claim is fresh / stale / expired against `claimed_at` + a TTL. One mechanism
 * for both halves of the board, which is also why both want the same dimmed,
 * draining treatment — `TtlBar` was already drawing it.
 *
 * **Two states are derived and never stored.** `unclaimed` is the absence of a
 * holder; `expired` is a lease nobody renewed, and writing it down would need a
 * process alive at the moment it drained — the exact thing that just stopped
 * being true.
 *
 * `renewed` is not a state: it is the event that keeps `held` fresh, which is
 * why it is not in the enum.
 *
 * Frozen in `contracts/board-vocabulary.json` under `assignment`; the CLI and the
 * backend carry their own copies, and a test on each side asserts against that
 * file so no copy can drift alone.
 */

import { fieldAsNumber, fieldAsString, ownerOf } from "./fields";
import type { LiveItem } from "./item";

export const ASSIGNMENT_FIELD = "assignment";

export const ASSIGNMENT_STATES = ["unclaimed", "held", "released", "expired", "resolved"] as const;
export type Assignment = (typeof ASSIGNMENT_STATES)[number];

/** What a writer may put on disk. The other two are read off the clock. */
export const STORED_ASSIGNMENT_STATES: Assignment[] = ["held", "released", "resolved"];
export const DERIVED_ASSIGNMENT_STATES: Assignment[] = ["unclaimed", "expired"];

/** The upstream half's three words, minus "missing": a claim expires. */
export const ASSIGNMENT_FRESHNESS = ["fresh", "stale", "expired"] as const;
export type AssignmentFreshness = (typeof ASSIGNMENT_FRESHNESS)[number];

/** Fraction of a lease that may be spent before a renewal is due. */
export const STALE_AFTER = 0.5;
export const DEFAULT_TTL_MINUTES = 30;

export const ASSIGNMENT_COMPANION_FIELDS = [
  "claimed_at",
  "ttl_minutes",
  "assignment_note",
  "assignment_note_by",
];

/** Who a note is attributed to when the runtime wrote it rather than a person. */
export const RUNTIME_AUTHOR = "runtime";

export const ATTENTION_OF_ASSIGNMENT: Record<Assignment, "needs_you" | "in_flight" | "resolved"> = {
  unclaimed: "needs_you",
  held: "in_flight",
  released: "needs_you",
  expired: "needs_you",
  resolved: "resolved",
};

/** Leases live on memories, because frontmatter has somewhere to put a stamp. */
export const ASSIGNABLE_NAMESPACES = ["work"];

/** Why a row refuses a claim, in its own terms. Saying so beats pretending. */
export const ASSIGNMENT_REFUSALS: Record<string, string> = {
  episode: "an episode is a recorded negotiation, and there is nothing to assign",
  agent: "presence is already a lease the runtime renews; it is not claimable",
  memory: "assignments live on work/ memories; this row is in another namespace",
};

/**
 * Assignment's own keys, which a plain field write must not touch.
 *
 * Derived from the model above rather than restated: a lease owns who holds a
 * row and for how long, under rules a field write cannot check — a live claim
 * is not stealable, and expiry is read off a clock rather than written down.
 * The backend refuses these too; this is so the surface can say why without
 * making the round trip.
 */
export const RESERVED_FIELDS = [ASSIGNMENT_FIELD, "owner", ...ASSIGNMENT_COMPANION_FIELDS];

/** Which of `names` a lease owns, so a caller can refuse before writing. */
export function reservedIn(names: string[]): string[] {
  return names.filter(n => RESERVED_FIELDS.includes(n)).sort();
}

/** A row is blocked because it names a blocker. Nothing stores the word. */
export const BLOCKED_FIELD = "blocked_by";

/**
 * When the holder last said it was still on this. A lease with no stamp of its
 * own falls back to when the row last moved: a hand-written `owner:` is still a
 * claim, and dating it from the file beats treating it as claimed now.
 */
export function claimedAt(item: LiveItem): string | null {
  return fieldAsString(item, "claimed_at") ?? fieldAsString(item, "updated");
}

/** Fraction of a lease already burned, or null when it cannot expire. */
export function leaseElapsedFraction(item: LiveItem, now: number): number | null {
  const raw = claimedAt(item);
  const ttl = fieldAsNumber(item, "ttl_minutes");
  if (raw === null || ttl === null || ttl <= 0) return null;
  const stamped = Date.parse(raw);
  if (Number.isNaN(stamped)) return null;
  return Math.max(0, (now - stamped) / 60000 / ttl);
}

export function leaseFreshness(item: LiveItem, now: number): AssignmentFreshness | null {
  const fraction = leaseElapsedFraction(item, now);
  if (fraction === null) return null;
  if (fraction < STALE_AFTER) return "fresh";
  return fraction < 1 ? "stale" : "expired";
}

/** Minutes of lease left, or null when the row does not expire. */
export function remainingMinutes(item: LiveItem, now: number): number | null {
  const fraction = leaseElapsedFraction(item, now);
  const ttl = fieldAsNumber(item, "ttl_minutes");
  if (fraction === null || ttl === null) return null;
  return Math.max(0, Math.round(ttl * (1 - fraction)));
}

/**
 * The row's assignment state, or null when it has no assignment axis.
 *
 * null is not a state — it means this row is not the kind of thing anyone holds
 * (a decision that has been made, a prose memory), so the filter falls back to its
 * stage rather than inventing a holder for it.
 *
 * A `held` lease whose clock ran out reads `expired` with nothing on disk having
 * changed: the row drains because time passed, not because anyone wrote it down.
 */
export function assignmentOf(item: LiveItem, now: number): Assignment | null {
  const stored = fieldAsString(item, ASSIGNMENT_FIELD);
  if (!stored || !(ASSIGNMENT_STATES as readonly string[]).includes(stored)) return null;
  if (stored !== "held") return stored as Assignment;
  // Held by nobody is not held. A row that lost its holder is in the pool.
  if (!ownerOf(item)) return "unclaimed";
  // A claim that cannot be shown to be alive is not evidence that it is — and an
  // undatable one (no stamp, or no window) is the purest form of the assertion
  // this model refuses: held forever, on nobody's word.
  const fresh = leaseFreshness(item, now);
  return fresh === "fresh" || fresh === "stale" ? "held" : "expired";
}

/** A row is blocked because it names a blocker, never because it says so. */
export function isBlocked(item: LiveItem): boolean {
  const value = item.fields[BLOCKED_FIELD];
  if (Array.isArray(value)) return value.length > 0;
  return typeof value === "string" && value.trim().length > 0;
}

export interface AssignmentNote {
  text: string;
  /** The releaser's handle, or `runtime` when the lease simply drained. */
  by: string;
}

/**
 * The row's assignment note and who wrote it, or null when there is none.
 *
 * Handing work off deliberately and dying mid-task converge on the same state:
 * an unclaimed row with history. What tells them apart is the note's author, so
 * both come back together rather than as prose a reader has to interpret.
 */
export function assignmentNote(item: LiveItem, now: number): AssignmentNote | null {
  if (assignmentOf(item, now) === "expired") {
    return {
      text: `expired — @${ownerOf(item) ?? "its holder"} stopped renewing`,
      by: RUNTIME_AUTHOR,
    };
  }
  const text = fieldAsString(item, "assignment_note");
  if (!text) return null;
  return { text, by: fieldAsString(item, "assignment_note_by") ?? RUNTIME_AUTHOR };
}

/** Why this row cannot take a lease, or null when it can. */
export function assignmentRefusal(item: LiveItem): string | null {
  const kind = item.source.kind;
  if (kind === "episode" || kind === "agent") return ASSIGNMENT_REFUSALS[kind];
  if (kind === "memory") {
    const namespace = fieldAsString(item, "namespace") ?? item.source.label.split("/")[0] ?? "";
    return ASSIGNABLE_NAMESPACES.includes(namespace) ? null : ASSIGNMENT_REFUSALS.memory;
  }
  return ASSIGNMENT_REFUSALS.memory;
}

/** The frontmatter a claim writes. One shape, whoever is claiming. */
export function claimPatch(
  handle: string,
  now: string,
  ttlMinutes = DEFAULT_TTL_MINUTES,
): Record<string, unknown> {
  return {
    [ASSIGNMENT_FIELD]: "held",
    owner: handle.startsWith("@") ? handle : `@${handle}`,
    claimed_at: now,
    ttl_minutes: ttlMinutes,
    // A new holder inherits the row, not the last holder's parting words.
    assignment_note: null,
    assignment_note_by: null,
  };
}

/** A deliberate handoff: no holder, and a note saying who let it go. */
export function releasePatch(
  handle: string,
  now: string,
  note?: string,
): Record<string, unknown> {
  return {
    [ASSIGNMENT_FIELD]: "released",
    owner: null,
    claimed_at: null,
    ttl_minutes: null,
    assignment_note: note || "released",
    assignment_note_by: handle.replace(/^@/, ""),
    updated: now,
  };
}
