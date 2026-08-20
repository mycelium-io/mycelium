// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** Per-room persistence for hand-arranged memory-graph positions (#599).
 *
 *  Kept in `localStorage` rather than on the hub: an arrangement is a personal
 *  view preference, not room state other members should inherit — the same call
 *  the command palette's recents make. Split out of the component so the
 *  pruning and schema rules below are unit-testable without rendering an SVG.
 */

export interface Point {
  x: number;
  y: number;
}

/** Hand-placed positions by memory key. */
export type Placements = Record<string, Point>;

const KEY_PREFIX = "mycelium.graph.layout.";

/** Bumped when the stored shape changes; anything else is discarded rather than
 *  migrated, since the cost of a lost arrangement is one drag. */
const SCHEMA = 1;

interface Stored {
  v: number;
  positions: Placements;
}

export function storageKeyFor(roomName: string): string {
  return `${KEY_PREFIX}${roomName}`;
}

function isPoint(value: unknown): value is Point {
  if (typeof value !== "object" || value === null) return false;
  const { x, y } = value as Partial<Point>;
  return typeof x === "number" && Number.isFinite(x) && typeof y === "number" && Number.isFinite(y);
}

/**
 * A room's saved arrangement, pruned to `known`.
 *
 * Pruning on read is what keeps this from accumulating junk: a memory that has
 * since been renamed or deleted leaves a position behind that can never be
 * reached again, and re-saving the pruned map drops it for good. Anything
 * malformed — bad JSON, a future schema, a non-finite coordinate — degrades to
 * "no arrangement" rather than throwing, because a corrupt preference must
 * never cost you the graph.
 */
export function loadPlacements(roomName: string, known: ReadonlySet<string>): Placements {
  if (typeof localStorage === "undefined") return {};
  try {
    const raw = localStorage.getItem(storageKeyFor(roomName));
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Partial<Stored>;
    if (parsed?.v !== SCHEMA || typeof parsed.positions !== "object" || parsed.positions === null) {
      return {};
    }
    const out: Placements = {};
    let dropped = false;
    for (const [key, point] of Object.entries(parsed.positions)) {
      if (known.has(key) && isPoint(point)) out[key] = { x: point.x, y: point.y };
      else dropped = true;
    }
    // Written back here, at the one moment we know something became
    // unreachable. The component only persists changes the *user* made, so if
    // pruning didn't clean up after itself the stale entry would ride along
    // forever — filtered on every read, but never actually gone.
    if (dropped) savePlacements(roomName, out);
    return out;
  } catch {
    // Unreadable store, or a jsdom-style stub whose methods are absent.
    return {};
  }
}

/** Persists an arrangement, or removes the entry entirely when it's empty —
 *  so "reset layout" leaves nothing behind rather than an empty husk. */
export function savePlacements(roomName: string, placements: Placements): void {
  if (typeof localStorage === "undefined") return;
  try {
    const storageKey = storageKeyFor(roomName);
    if (Object.keys(placements).length === 0) {
      localStorage.removeItem(storageKey);
      return;
    }
    const payload: Stored = { v: SCHEMA, positions: placements };
    localStorage.setItem(storageKey, JSON.stringify(payload));
  } catch {
    // A full, blocked, or stubbed store costs the arrangement, not the graph.
  }
}
