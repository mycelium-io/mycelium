// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, type RefObject } from "react";

/** How close to the top older rows start loading, and how close to the bottom
 *  still counts as "following the conversation". */
const LOAD_MARGIN_PX = 300;
const BOTTOM_SLACK_PX = 80;

interface ReverseScrollOptions {
  /** The scrolling element the sentinel lives inside. */
  viewportRef: RefObject<HTMLElement | null>;
  /** How many rows are rendered — the signal that a prepend has landed. */
  itemCount: number;
  /** Off once history is exhausted, or before the first page has arrived. */
  enabled: boolean;
  /** Load the next page of older rows; resolves with how many were added. */
  onLoadOlder: () => Promise<number>;
}

/**
 * Load older rows when the reader scrolls to the top, without moving the page
 * under them.
 *
 * Prepending rows grows the document upward, so a viewport that holds its
 * `scrollTop` appears to leap backward through the conversation. This measures
 * the reader's distance from the *bottom* before the load and restores that
 * distance after the rows land, which leaves the row they were reading exactly
 * where it was.
 *
 * Attach the returned ref to an element at the very top of the list.
 */
export function useReverseScroll({
  viewportRef,
  itemCount,
  enabled,
  onLoadOlder,
}: ReverseScrollOptions): RefObject<HTMLDivElement | null> {
  const sentinelRef = useRef<HTMLDivElement>(null);
  // Distance from the bottom, held between asking for a page and its rows
  // arriving. Null when no load is outstanding.
  const anchor = useRef<number | null>(null);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || anchor.current === null) return;
    viewport.scrollTop = viewport.scrollHeight - anchor.current;
    anchor.current = null;
  }, [itemCount, viewportRef]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    const viewport = viewportRef.current;
    if (!enabled || !sentinel || !viewport || typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        // The observer keeps firing while the sentinel stays in view; only the
        // call that takes the anchor may release it, so a repeat can't drop the
        // measurement the outstanding load is going to restore.
        const claimed = anchor.current === null;
        if (claimed) anchor.current = viewport.scrollHeight - viewport.scrollTop;
        void onLoadOlder().then((added) => {
          if (!added && claimed) anchor.current = null;
        });
      },
      { root: viewport, rootMargin: `${LOAD_MARGIN_PX}px 0px 0px 0px` },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [enabled, onLoadOlder, viewportRef]);

  return sentinelRef;
}

/**
 * Whether the feed should still follow new rows to the bottom.
 *
 * A reader parked at the bottom wants each new message brought into view; a
 * reader who has scrolled up — to read history, or because a page of it just
 * loaded — does not, and yanking them down loses their place. Call the returned
 * function before auto-scrolling.
 */
export function useStickToBottom(viewportRef: RefObject<HTMLElement | null>): () => boolean {
  const following = useRef(true);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const onScroll = () => {
      const distance = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
      following.current = distance <= BOTTOM_SLACK_PX;
    };
    onScroll();
    viewport.addEventListener("scroll", onScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", onScroll);
  }, [viewportRef]);

  return useCallback(() => following.current, []);
}
