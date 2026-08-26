// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef, type RefObject } from "react";

export interface MinimapTick {
  /** The message the tick stands for. */
  id: string;
  /** Where it sits in the scrollable content, 0 at the top and 1 at the end. */
  top: number;
}

interface Props {
  viewportRef: RefObject<HTMLDivElement | null>;
  ticks: MinimapTick[];
  activeId: string | null;
  onJump: (id: string) => void;
}

/** The scroll gutter as a map of the search: one tick per matching message,
 *  drawn where that message actually sits in the whole scrollable feed.
 *
 *  This is the thing an editor's scrollbar does — it answers *where* the hits
 *  are, and how they are clustered, before you have stepped through any of
 *  them. Three matches at the very top of a long backlog is a different room
 *  from thirty spread evenly down it, and the counter alone cannot say which
 *  one you are in.
 *
 *  The pale box is the part of the feed currently on screen, so a tick can be
 *  read as near or far rather than only as high or low. It is written straight
 *  to the node's style on scroll: a rail that re-rendered the feed on every
 *  wheel tick would cost more than it tells anyone. */
export function ChatMinimap({ viewportRef, ticks, activeId, onJump }: Props) {
  const windowBox = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = viewportRef.current;
    const box = windowBox.current;
    if (!el || !box) return;
    const paint = () => {
      const height = el.scrollHeight || 1;
      box.style.top = `${Math.min(100, (el.scrollTop / height) * 100)}%`;
      box.style.height = `${Math.min(100, (el.clientHeight / height) * 100)}%`;
    };
    paint();
    el.addEventListener("scroll", paint, { passive: true });
    const observer = new ResizeObserver(paint);
    observer.observe(el);
    return () => {
      el.removeEventListener("scroll", paint);
      observer.disconnect();
    };
  }, [viewportRef, ticks]);

  return (
    <div
      data-slot="chat-minimap"
      // Unpainted, so the viewport's own scrollbar still reads and still takes
      // a drag through it: the ticks ride the track the way an editor's do,
      // rather than replacing it with a second rail beside it.
      className="pointer-events-none absolute inset-y-0 right-0 z-20 w-3"
    >
      {/* The part of the feed on screen. The real thumb says this too, but only
          while it is being used; this is the version that is there at rest. */}
      <div ref={windowBox} className="absolute inset-x-0 rounded-[1px] bg-text/[0.06]" />
      {ticks.map((tick, i) => {
        const active = tick.id === activeId;
        return (
          <button
            key={tick.id}
            type="button"
            onClick={() => onJump(tick.id)}
            aria-label={`Jump to match ${i + 1} of ${ticks.length}`}
            style={{ top: `${(tick.top * 100).toFixed(3)}%` }}
            className={`pointer-events-auto absolute inset-x-0.5 -translate-y-1/2 rounded-full transition-colors ${
              active ? "h-[5px] bg-accent ring-1 ring-accent/40" : "h-[3px] bg-yellow hover:bg-yellow/70"
            }`}
          />
        );
      })}
    </div>
  );
}
