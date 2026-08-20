// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Reading a paginated list from the hub.
 *
 * Every list the backend serves pages the same way (`app/services/pagination.py`):
 * ask with a `cursor`, get back a page plus the `next_cursor` that continues it,
 * and a null cursor means the end. The cursor names a row rather than a position,
 * so a reader walking back through history keeps its place while the list grows
 * at the head — which is what makes reverse scroll in a live room possible at all.
 *
 * This module is the merge half of that: pure functions a component can test
 * without a DOM. The fetching half is `use-cursor-pagination`.
 */

import type { CursorPage } from "@/lib/api";

/** One page as the hub returns it: the rows, plus where to continue. */
export interface CursorPageOf<T> extends CursorPage {
  items: T[];
}

/**
 * Fold an older page into a list that already holds newer rows.
 *
 * Older rows go in front, and any row already present is dropped rather than
 * repeated: a page of history and the live stream can name the same message, and
 * the reader must see it once. Identity comes from `keyOf`; a row with no key
 * (nothing to compare) is kept, since dropping it would lose history.
 */
export function mergeOlder<T>(
  existing: T[],
  older: T[],
  keyOf: (row: T) => string | null | undefined,
): T[] {
  const known = new Set(existing.map(keyOf).filter(Boolean) as string[]);
  const fresh = older.filter((row) => {
    const key = keyOf(row);
    if (!key) return true;
    if (known.has(key)) return false;
    known.add(key);
    return true;
  });
  return fresh.length ? [...fresh, ...existing] : existing;
}
