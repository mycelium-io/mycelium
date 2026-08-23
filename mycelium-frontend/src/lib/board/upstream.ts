// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Put a status provider's answer on the row that mentioned it.
 *
 * The hub resolves every external reference a room's text names and returns
 * them keyed by the board row ids that mention them, so this does no parsing:
 * it looks up a row's id and lands the answer under `upstream`.
 *
 * **The state is the field; the rest are companions.** `upstream` carries the
 * state alone (a closed vocabulary the board can group, filter and colour by,
 * the same way it treats `status` and `ci`) rather than an object, which
 * inference would type as free text and no view could group. The provider's own
 * wording, its link and the answer's age ride alongside in their own fields,
 * which is how a row already carries `pr`, `ci` and `branch`.
 *
 * **A row that names two things shows the worse one.** Rows are how a board says
 * what needs you, so a task blocked on one pull request and green on another
 * reads as blocked; `upstream_count` says there was more than one, so the
 * summary never quietly stands in for the whole.
 *
 * **Not knowing yet is not a state.** The hub answers a read from cache and
 * refreshes behind it, so the first read of a room has references but no answers
 * for them. That is `upstream_pending`, and deliberately not `unknown`, which is
 * a real thing a provider says when it meets a state it cannot place. A row that
 * is pending carries no `upstream` at all, so a board grouping by the field
 * never collects a bucket of rows that were merely early.
 */

import type { LiveItem } from "./item";

/**
 * Worst first. A row with several references takes the first state in this
 * order that any of them is in, because a board exists to surface the thing
 * that needs a person, not to average.
 */
export const UPSTREAM_STATES = ["failed", "blocked", "pending", "ok", "done", "unknown"] as const;

export type UpstreamState = (typeof UPSTREAM_STATES)[number];

export const UPSTREAM_FIELD = "upstream";

/** One resolved reference, as `GET /rooms/{room}/status` returns it. */
export interface UpstreamRef {
  ref: string;
  provider: string;
  kind: string;
  id: string;
  url: string | null;
  freshness: "fresh" | "stale" | "missing" | "error";
  state: UpstreamState | null;
  label: string | null;
  age_seconds: number | null;
  error: string | null;
  origins: string[];
}

export interface RoomStatus {
  room: string;
  field: string;
  providers: string[];
  refs: UpstreamRef[];
  rows: Record<string, string[]>;
  refreshing: boolean;
}

function rank(state: string | null | undefined): number {
  const i = (UPSTREAM_STATES as readonly string[]).indexOf(state ?? "unknown");
  return i === -1 ? UPSTREAM_STATES.length : i;
}

/**
 * A human reading of how old an answer is, in the same shape a row's other ages
 * take. An answer with no age was never fetched, and says nothing.
 */
export function upstreamAge(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined) return null;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`;
}

/**
 * Land each row's upstream answer on it, returning new rows.
 *
 * A row nothing was found for is returned untouched: no field, rather than an
 * empty one, so a view can tell "nothing upstream" from "upstream unknown".
 */
export function attachUpstream(items: LiveItem[], status: RoomStatus | null | undefined): LiveItem[] {
  if (!status) return items;

  const byRef = new Map(status.refs.map(r => [r.ref, r]));
  const rows = status.rows ?? {};

  return items.map(item => {
    const answers = (rows[item.id] ?? [])
      .map(ref => byRef.get(ref))
      .filter((r): r is UpstreamRef => r !== undefined);
    if (answers.length === 0) return item;

    // A resolved answer outranks one still coming, so a row with two references
    // shows what is known rather than waiting on the slowest.
    answers.sort((a, b) => {
      const known = Number(b.state !== null) - Number(a.state !== null);
      return known !== 0 ? known : rank(a.state) - rank(b.state);
    });
    const worst = answers[0];

    // Nothing has come back for this row yet. Say so, rather than showing a
    // state nobody reported.
    if (worst.state === null) {
      return {
        ...item,
        fields: {
          ...item.fields,
          upstream_pending: worst.freshness === "missing" || status.refreshing,
          upstream_label: worst.error,
          upstream_freshness: worst.freshness,
          ...(answers.length > 1 ? { upstream_count: answers.length } : {}),
        },
      };
    }

    return {
      ...item,
      fields: {
        ...item.fields,
        [UPSTREAM_FIELD]: worst.state,
        // An errored answer has no label of its own, so the reason stands in:
        // "not visible to this token" is the honest wording for that row.
        upstream_label: worst.label ?? worst.error,
        upstream_url: worst.url,
        upstream_age: upstreamAge(worst.age_seconds),
        upstream_freshness: worst.freshness,
        ...(answers.length > 1 ? { upstream_count: answers.length } : {}),
      },
    };
  });
}
