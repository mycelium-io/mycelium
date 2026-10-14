// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** A reader a couple of lines off the bottom still counts as reading the tail,
 *  so a stray wheel tick doesn't detach them. */
export const AT_BOTTOM_PX = 64;

/** How close to the top counts as asking for the page before. */
export const NEAR_TOP_PX = 240;

/** Longer than a smooth jump to the latest takes; past it, a scroll is the reader's. */
const JUMP_SETTLE_MS = 1000;

/** To the newest row, at once: animated, the scroll lands short of a tail that
 *  grows while it runs, and the list then reads the reader as having left it. */
function toBottom(node: HTMLElement) {
  node.scrollTo({ top: node.scrollHeight, behavior: "instant" });
}

export interface FollowOptions {
  /** Every row the list draws, oldest first, by a stable id; `null` until the
   *  first page has loaded, so loading never reads as messages arriving. */
  rows: readonly string[] | null;
  /** The rows "N new" counts, when that is fewer than all of them (the Stream
   *  counts messages, not board lines). Defaults to `rows`. */
  counted?: readonly string[] | null;
  /** Where the list opens: at its newest row, or at the top (a task's page opens
   *  on the task, with its thread below). */
  startAt?: "end" | "start";
  /** While the reader is on something they were taken to (a search hit, a
   *  linked message), nothing pulls the view away from it. */
  holding?: boolean;
  /** Asked for when the reader nears the top, or when what has loaded doesn't
   *  fill the view: read back a page. A page that lands above keeps the reader
   *  where they were. Asked on every scroll event near the top, so it must
   *  ignore a call while a page is already on its way (the channel and a
   *  thread both do). */
  onNearTop?: () => void;
  /** Changes when the reader sends: what they sent is where they are looking,
   *  so the view goes back to the newest row and follows from there. */
  sent?: string | null;
  /** What the rows belong to (a room, a memory, a filter). When it changes the
   *  list starts over: it opens again and counts from nothing. */
  resetKey?: string;
}

export interface Follow {
  /** Whether the reader is at the newest row. */
  atBottom: boolean;
  /** How many counted rows arrived since the reader left the bottom. */
  unread: number;
  /** Back to the newest row. */
  jump: () => void;
}

/**
 * The one scroll behavior every message list has: the channel, a task's
 * thread, a memory's discussion and the Stream.
 *
 * Where the reader is, is tracked as they scroll, never measured after a row
 * lands, so a tall reply arriving can't count against them. While they're at
 * the bottom the view stays there through anything: a new row, a message
 * growing (an image loading, a long reply expanding), the composer changing
 * size. Scrolled up, it holds still, says how much arrived meanwhile, and
 * reading near the top asks for older messages without moving what's on screen.
 *
 * `el` is the scrolling element, passed as state (a callback ref), so the
 * listeners attach once it exists.
 */
export function useFollowLatest(
  el: HTMLElement | null,
  { rows, counted = rows, startAt = "end", holding = false, onNearTop, sent = null, resetKey }: FollowOptions,
): Follow {
  const startsAtEnd = startAt === "end";
  const [atBottom, setAtBottom] = useState(startsAtEnd);
  const atBottomRef = useRef(startsAtEnd);
  const holdingRef = useRef(holding);
  const onNearTopRef = useRef(onNearTop);
  const countedRef = useRef(counted);
  // What the rows belong to, and whether the list has opened on them yet.
  const keyRef = useRef(resetKey);
  const landed = useRef(false);
  // The element, read through a ref where the scroll is moved: `el` itself is
  // state, and only names when the listeners should attach.
  const elRef = useRef<HTMLElement | null>(el);
  useLayoutEffect(() => {
    elRef.current = el;
    holdingRef.current = holding;
    onNearTopRef.current = onNearTop;
    countedRef.current = counted;
  });

  // The last counted row the reader had reached when they left the bottom,
  // and every counted row there was then. The row, not a count: a page of
  // older messages lands above it, and none of that is news. The set answers
  // once the mark itself has scrolled out of a list that keeps only so many.
  const [detached, setDetached] = useState<{ key: string | undefined; mark: string | null; seen: Set<string> } | null>(
    null,
  );
  const detach = useCallback(() => {
    const ids = countedRef.current ?? [];
    setDetached({ key: keyRef.current, mark: ids[ids.length - 1] ?? null, seen: new Set(ids) });
  }, []);

  const setBottom = useCallback(
    (pinned: boolean) => {
      if (pinned === atBottomRef.current) return;
      atBottomRef.current = pinned;
      setAtBottom(pinned);
      if (pinned) setDetached(null);
      else detach();
    },
    [detach],
  );

  // Where the list opens can still change until it has: the page may learn
  // what it is showing (a task, or a bare thread) after it first draws.
  useLayoutEffect(() => {
    if (landed.current || atBottomRef.current === startsAtEnd) return;
    atBottomRef.current = startsAtEnd;
    setAtBottom(startsAtEnd);
  }, [startsAtEnd]);

  // What the rows belong to: a change starts the list over.
  useLayoutEffect(() => {
    if (keyRef.current === resetKey) return;
    keyRef.current = resetKey;
    landed.current = false;
    atBottomRef.current = startsAtEnd;
    setAtBottom(startsAtEnd);
    setDetached(null);
  }, [resetKey, startsAtEnd]);

  // Where the reader stands, kept as they scroll: the distance from the bottom
  // is what a page landing above changes, so it is what puts them back.
  const fromBottom = useRef(0);
  const firstRow = useRef<string | null>(null);
  // Set while a jump to the latest scrolls down, until it gets there (or gives
  // up: a reader who scrolls during it has stopped the animation).
  const arriving = useRef(false);
  const arrivingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (arrivingTimer.current) clearTimeout(arrivingTimer.current);
  }, []);

  useEffect(() => {
    if (!el) return;
    const measure = () => {
      fromBottom.current = el.scrollHeight - el.scrollTop;
      if (el.scrollTop <= NEAR_TOP_PX) onNearTopRef.current?.();
      const pinned = el.scrollHeight - el.scrollTop - el.clientHeight <= AT_BOTTOM_PX;
      // Jumping to the latest is still on its way down: its own scroll events
      // aren't the reader leaving the bottom.
      if (arriving.current) {
        if (!pinned) return;
        arriving.current = false;
      }
      setBottom(pinned);
    };
    el.addEventListener("scroll", measure, { passive: true });
    // On the tail, stay on it through anything that changes the list's size
    // rather than its rows: a message growing, the view getting shorter.
    // Neither scrolls, so without this the newest line slides out of view.
    const stick = () => {
      if (atBottomRef.current && !holdingRef.current) el.scrollTop = el.scrollHeight;
      fromBottom.current = el.scrollHeight - el.scrollTop;
    };
    if (typeof ResizeObserver === "undefined") return () => el.removeEventListener("scroll", measure);
    const observer = new ResizeObserver(stick);
    // The view, and what's in it, including what replaces it (a skeleton
    // giving way to the list).
    const watch = () => {
      for (const child of el.children) observer.observe(child);
    };
    observer.observe(el);
    watch();
    const swapped = typeof MutationObserver === "undefined" ? null : new MutationObserver(watch);
    swapped?.observe(el, { childList: true });
    return () => {
      el.removeEventListener("scroll", measure);
      observer.disconnect();
      swapped?.disconnect();
    };
  }, [el, setBottom]);

  // Rows changed: open the list the first time, keep the reader's place when a
  // page landed above, and follow the tail when they're on it. Before paint,
  // and at once: an animated scroll lands short of a tail that grows while it
  // runs, and the list then reads the reader as having left it.
  useLayoutEffect(() => {
    const node = elRef.current;
    if (!node || rows === null) return;
    const first = rows[0] ?? null;
    const before = firstRow.current;
    firstRow.current = first;
    if (!landed.current) {
      if (rows.length === 0) return;
      landed.current = true;
      if (startsAtEnd) {
        if (!holdingRef.current) toBottom(node);
      } else {
        // Opened at the top, it stays there until the reader goes down, even
        // when it all fits: what's above (a task's body) can still be drawing,
        // and following its growth would scroll the top out of view. What
        // arrives meanwhile is counted.
        atBottomRef.current = false;
        // eslint-disable-next-line react-hooks/set-state-in-effect -- once, when the list first opens
        setAtBottom(false);
        detach();
      }
      fromBottom.current = node.scrollHeight - node.scrollTop;
      return;
    }
    const prepended = before !== null && first !== before && rows.includes(before);
    if (prepended && !atBottomRef.current) {
      node.scrollTop = node.scrollHeight - fromBottom.current;
    } else if (atBottomRef.current && !holdingRef.current) {
      toBottom(node);
    }
    fromBottom.current = node.scrollHeight - node.scrollTop;
  }, [el, rows, startsAtEnd, detach]);

  // What has loaded doesn't fill the view: there is no scrolling up to ask for
  // more, so ask now. A view with no height isn't laid out (hidden, or not yet
  // sized), not empty: filling it would read back the whole history.
  useEffect(() => {
    const node = elRef.current;
    if (!node || rows === null || !onNearTopRef.current || node.clientHeight === 0) return;
    if (node.scrollHeight <= node.clientHeight + NEAR_TOP_PX) onNearTopRef.current();
  }, [el, rows]);

  // What you just sent is where you are looking.
  useLayoutEffect(() => {
    const node = elRef.current;
    if (!node || !sent) return;
    atBottomRef.current = true;
    setAtBottom(true);
    setDetached(null);
    toBottom(node);
  }, [el, sent]);

  const jump = useCallback(() => {
    const node = elRef.current;
    if (!node) return;
    atBottomRef.current = true;
    setAtBottom(true);
    setDetached(null);
    arriving.current = true;
    if (arrivingTimer.current) clearTimeout(arrivingTimer.current);
    arrivingTimer.current = setTimeout(() => {
      arriving.current = false;
    }, JUMP_SETTLE_MS);
    node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
  }, []);

  let unread = 0;
  if (!atBottom && detached && detached.key === resetKey && counted) {
    const at = detached.mark === null ? -1 : counted.lastIndexOf(detached.mark);
    unread =
      at !== -1 || detached.mark === null
        ? counted.length - 1 - at
        : counted.filter((id) => !detached.seen.has(id)).length;
  }
  return { atBottom, unread, jump };
}

/** What a conversation drawn inside a page tells the page, for the scroll they
 *  share: its rows, what was just sent, and how to read back. */
export interface ConversationRows {
  /** The rows drawn, oldest first; `null` until the thread has loaded. */
  rows: string[] | null;
  /** The newest message sent from here that hasn't landed yet. */
  sent: string | null;
  /** Read back a page, when there is one. */
  onNearTop?: () => void;
}

const NOT_LOADED: ConversationRows = { rows: null, sent: null };

/**
 * The same scroll behavior, for a page whose scroll holds more than the
 * conversation (a task's body above its thread): the page owns the scrolling
 * element, the conversation inside it reports what it draws through `onRows`.
 */
export function useConversationFollow(
  el: HTMLElement | null,
  { startAt, resetKey }: Pick<FollowOptions, "startAt" | "resetKey">,
): Follow & { onRows: (rows: ConversationRows) => void; hasRows: boolean } {
  const [report, setReport] = useState<ConversationRows>(NOT_LOADED);
  const follow = useFollowLatest(el, { ...report, startAt, resetKey });
  return { ...follow, onRows: setReport, hasRows: (report.rows?.length ?? 0) > 0 };
}
