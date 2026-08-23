// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Custody: who holds a row, and for how much longer.
 *
 * An agent is resident rather than one-shot, but no session gets to announce
 * that it ended — a container is reclaimed, a cloud session times out, a job is
 * cancelled. So every assertion an ephemeral actor makes about the future is a
 * lease, because none of them can promise the future.
 *
 * Held as a fact, one dead agent leaves the board asserting "@someone is on
 * this" forever, and the board degrades exactly as it gets busy: full of
 * confident lies. Held as a lease, an abandoned claim drains and the row returns
 * to the pool.
 *
 * **Custody is not a stage.** `status` is a stage vocabulary, borrowed from
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
 * Frozen in `contracts/board-vocabulary.json` under `custody`; the CLI and the
 * backend carry their own copies, and a test on each side asserts against that
 * file so no copy can drift alone.
 */

import { num, ownerOf, str } from "./fields";
import type { LiveItem } from "./item";

export const CUSTODY_FIELD = "custody";

export const CUSTODY_STATES = ["unclaimed", "held", "released", "expired", "resolved"] as const;
export type Custody = (typeof CUSTODY_STATES)[number];

/** What a writer may put on disk. The other two are read off the clock. */
export const STORED_CUSTODY_STATES: Custody[] = ["held", "released", "resolved"];
export const DERIVED_CUSTODY_STATES: Custody[] = ["unclaimed", "expired"];

/** The upstream half's three words, minus "missing": a claim expires. */
export const CUSTODY_FRESHNESS = ["fresh", "stale", "expired"] as const;
export type CustodyFreshness = (typeof CUSTODY_FRESHNESS)[number];

/** Fraction of a lease that may be spent before a renewal is due. */
export const STALE_AFTER = 0.5;
export const DEFAULT_TTL_MINUTES = 30;

export const CUSTODY_COMPANION_FIELDS = [
  "claimed_at",
  "ttl_minutes",
  "custody_note",
  "custody_note_by",
];

/** Who a note is attributed to when the runtime wrote it rather than a person. */
export const RUNTIME_AUTHOR = "runtime";

export const LENS_OF_CUSTODY: Record<Custody, "needs_you" | "in_flight" | "resolved"> = {
  unclaimed: "needs_you",
  held: "in_flight",
  released: "needs_you",
  expired: "needs_you",
  resolved: "resolved",
};

/** Leases live on memories, because frontmatter has somewhere to put a stamp. */
export const LEASABLE_NAMESPACES = ["work"];

/** Why a row refuses a claim, in its own terms. Saying so beats pretending. */
export const CUSTODY_REFUSALS: Record<string, string> = {
  plan: "a plan task is the room's commitment, not a lease: assign it with @handle",
  episode: "an episode is a recorded negotiation, and there is nothing to write a lease onto",
  agent: "presence is already a lease the runtime renews; it is not claimable",
  memory: "leases live on work/ memories; this row is in another namespace",
};

/** A row is blocked because it names a blocker. Nothing stores the word. */
export const BLOCKED_FIELD = "blocked_by";

/**
 * When the holder last said it was still on this. A lease with no stamp of its
 * own falls back to when the row last moved: a hand-written `owner:` is still a
 * claim, and dating it from the file beats treating it as claimed now.
 */
export function claimedAt(item: LiveItem): string | null {
  return str(item, "claimed_at") ?? str(item, "updated");
}

/** Fraction of a lease already burned, or null when it cannot expire. */
export function leaseSpent(item: LiveItem, now: number): number | null {
  const raw = claimedAt(item);
  const ttl = num(item, "ttl_minutes");
  if (raw === null || ttl === null || ttl <= 0) return null;
  const stamped = Date.parse(raw);
  if (Number.isNaN(stamped)) return null;
  return Math.max(0, (now - stamped) / 60000 / ttl);
}

export function leaseFreshness(item: LiveItem, now: number): CustodyFreshness | null {
  const fraction = leaseSpent(item, now);
  if (fraction === null) return null;
  if (fraction < STALE_AFTER) return "fresh";
  return fraction < 1 ? "stale" : "expired";
}

/** Minutes of lease left, or null when the row does not expire. */
export function remainingMinutes(item: LiveItem, now: number): number | null {
  const fraction = leaseSpent(item, now);
  const ttl = num(item, "ttl_minutes");
  if (fraction === null || ttl === null) return null;
  return Math.max(0, Math.round(ttl * (1 - fraction)));
}

/**
 * The row's custody state, or null when it has no custody axis.
 *
 * null is not a state — it means this row is not the kind of thing anyone holds
 * (a decision that has been made, a prose memory), so a lens falls back to its
 * stage rather than inventing a holder for it.
 *
 * A `held` lease whose clock ran out reads `expired` with nothing on disk having
 * changed: the row drains because time passed, not because anyone wrote it down.
 */
export function custodyOf(item: LiveItem, now: number): Custody | null {
  const stored = str(item, CUSTODY_FIELD);
  if (!stored || !(CUSTODY_STATES as readonly string[]).includes(stored)) return null;
  if (stored !== "held") return stored as Custody;
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

export interface CustodyNote {
  text: string;
  /** The releaser's handle, or `runtime` when the lease simply drained. */
  by: string;
}

/**
 * The row's custody note and who wrote it, or null when there is none.
 *
 * Handing work off deliberately and dying mid-task converge on the same state:
 * an unclaimed row with history. What tells them apart is the note's author, so
 * both come back together rather than as prose a reader has to interpret.
 */
export function custodyNote(item: LiveItem, now: number): CustodyNote | null {
  if (custodyOf(item, now) === "expired") {
    return {
      text: `expired — @${ownerOf(item) ?? "its holder"} stopped renewing`,
      by: RUNTIME_AUTHOR,
    };
  }
  const text = str(item, "custody_note");
  if (!text) return null;
  return { text, by: str(item, "custody_note_by") ?? RUNTIME_AUTHOR };
}

/** Why this row cannot take a lease, or null when it can. */
export function custodyRefusal(item: LiveItem): string | null {
  const kind = item.source.kind;
  if (kind === "plan" || kind === "episode" || kind === "agent") return CUSTODY_REFUSALS[kind];
  if (kind === "memory") {
    const namespace = str(item, "namespace") ?? item.source.label.split("/")[0] ?? "";
    return LEASABLE_NAMESPACES.includes(namespace) ? null : CUSTODY_REFUSALS.memory;
  }
  return CUSTODY_REFUSALS.memory;
}

/** The frontmatter a claim writes. One shape, whoever is claiming. */
export function claimPatch(
  handle: string,
  now: string,
  ttlMinutes = DEFAULT_TTL_MINUTES,
): Record<string, unknown> {
  return {
    [CUSTODY_FIELD]: "held",
    owner: handle.startsWith("@") ? handle : `@${handle}`,
    claimed_at: now,
    ttl_minutes: ttlMinutes,
    // A new holder inherits the row, not the last holder's parting words.
    custody_note: null,
    custody_note_by: null,
  };
}

/** A deliberate handoff: no holder, and a note saying who let it go. */
export function releasePatch(
  handle: string,
  now: string,
  note?: string,
): Record<string, unknown> {
  return {
    [CUSTODY_FIELD]: "released",
    owner: null,
    claimed_at: null,
    ttl_minutes: null,
    custody_note: note || "released",
    custody_note_by: handle.replace(/^@/, ""),
    updated: now,
  };
}
