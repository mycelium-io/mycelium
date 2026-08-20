// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CursorPageOf } from "@/lib/cursor-pagination";

/**
 * Walk a cursor-paginated list one page at a time.
 *
 * Holds the cursor, the in-flight guard, and whether the list is exhausted —
 * the state every paged reader needs and none of them should re-invent. It
 * deliberately does *not* own the rows: a chat feed merges pages into a list the
 * live stream is also writing to, so merging belongs to the caller (`mergeOlder`).
 *
 *     const { loadMore, loading, exhausted } = useCursorPagination(
 *       (cursor) => fetchMessages(room, 50, cursor).then((r) => ({ ...r, items: r.messages })),
 *       room,
 *     );
 *
 * `resetKey` re-arms the walk from the top when it changes (a different room is
 * a different list). `loadMore` resolves with the page's rows, or an empty array
 * when there is nothing left, a request is already in flight, or the fetch fails
 * — a page that can't load is a page not shown, never a broken feed.
 */
export function useCursorPagination<T>(
  fetchPage: (cursor: string | null) => Promise<CursorPageOf<T>>,
  resetKey?: unknown,
) {
  const [loading, setLoading] = useState(false);
  const [exhausted, setExhausted] = useState(false);
  const cursor = useRef<string | null>(null);
  const inFlight = useRef(false);
  // Which list the walk is on. A request outlives a reset — switch rooms with a
  // page in flight and it lands after — so a page from a superseded walk is
  // dropped rather than merged into whatever the reader is now looking at.
  const walk = useRef(0);
  // Held in a ref so a caller passing an inline closure (the usual case) doesn't
  // re-create loadMore on every render and re-fire the effects watching it.
  const fetcher = useRef(fetchPage);
  fetcher.current = fetchPage;

  useEffect(() => {
    walk.current += 1;
    cursor.current = null;
    inFlight.current = false;
    setExhausted(false);
    setLoading(false);
  }, [resetKey]);

  const loadMore = useCallback(async (): Promise<T[]> => {
    if (inFlight.current) return [];
    const mine = walk.current;
    inFlight.current = true;
    setLoading(true);
    try {
      const page = await fetcher.current(cursor.current);
      if (mine !== walk.current) return [];
      cursor.current = page.next_cursor ?? null;
      if (!page.next_cursor || page.has_more === false) setExhausted(true);
      return page.items;
    } catch {
      if (mine === walk.current) setExhausted(true); // stop asking a list that can't answer
      return [];
    } finally {
      if (mine === walk.current) {
        inFlight.current = false;
        setLoading(false);
      }
    }
  }, []);

  return { loadMore, loading, exhausted };
}
