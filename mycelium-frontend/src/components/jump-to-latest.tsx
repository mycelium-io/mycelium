// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";

/** The pill that floats over the bottom of a conversation once the reader has
 *  scrolled up off its newest message: "Jump to latest", or "3 new messages"
 *  when messages have landed meanwhile. Its parent must be `relative`. */
export function JumpToLatest({ unread, onClick }: { unread: number; onClick: () => void }) {
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-3 flex justify-center">
      <Button
        size="sm"
        variant="secondary"
        onClick={onClick}
        aria-label={unread > 0 ? `Jump to latest, ${unread} new` : "Jump to latest"}
        className="pointer-events-auto rounded-full border-border bg-elevated shadow-lg motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-1"
      >
        <ArrowDown className="size-3.5" />
        {unread > 0 ? `${unread} new ${unread === 1 ? "message" : "messages"}` : "Jump to latest"}
      </Button>
    </div>
  );
}

/** How close to the bottom counts as being there. */
const AT_BOTTOM_PX = 64;

/**
 * Whether a scroll region is at its bottom, and how many messages arrived since
 * the reader left it, for a page whose newest message is at the end (a memory
 * with its discussion under it). `count` is how many messages the page shows,
 * or `null` until they have loaded, so the first batch never reads as new.
 * `resetKey` names what the messages belong to (a memory's key): when it
 * changes, the count starts over rather than measuring one memory's replies
 * against another's.
 */
export function useJumpToLatest(el: HTMLElement | null, count: number | null, resetKey?: string) {
  const [atBottom, setAtBottom] = useState(true);
  const atBottomRef = useRef(true);
  // How many messages there were when the reader left the bottom, and for
  // which `resetKey`: a baseline from another key doesn't count.
  const [leftAt, setLeftAt] = useState<{ key: string | undefined; count: number | null } | null>(null);
  const countAtLeave = leftAt && leftAt.key === resetKey ? leftAt.count : null;
  const countRef = useRef(count);
  const keyRef = useRef(resetKey);
  const setCountAtLeave = useCallback(
    (n: number | null) => setLeftAt(n === null ? null : { key: keyRef.current, count: n }),
    [],
  );
  useEffect(() => {
    countRef.current = count;
    keyRef.current = resetKey;
  }, [count, resetKey]);

  useEffect(() => {
    if (!el) return;
    const measure = () => {
      const pinned = el.scrollHeight - el.scrollTop - el.clientHeight <= AT_BOTTOM_PX;
      if (pinned === atBottomRef.current) return;
      atBottomRef.current = pinned;
      setAtBottom(pinned);
      setCountAtLeave(pinned ? null : countRef.current);
    };
    measure();
    el.addEventListener("scroll", measure, { passive: true });
    // Content growing (the discussion loading, a long body) moves the bottom
    // without any scrolling.
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    if (el.firstElementChild) observer.observe(el.firstElementChild);
    return () => {
      el.removeEventListener("scroll", measure);
      observer.disconnect();
    };
  }, [el, setCountAtLeave]);

  // Left the bottom before the messages loaded (or before switching to other
  // messages): count from when they did.
  useEffect(() => {
    if (!atBottom && countAtLeave === null && count !== null) setCountAtLeave(count);
  }, [atBottom, countAtLeave, count, setCountAtLeave]);

  const unread = atBottom || countAtLeave === null || count === null ? 0 : Math.max(0, count - countAtLeave);
  const jump = () => {
    if (!el) return;
    atBottomRef.current = true;
    setAtBottom(true);
    setCountAtLeave(null);
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };
  return { atBottom, unread, jump };
}
