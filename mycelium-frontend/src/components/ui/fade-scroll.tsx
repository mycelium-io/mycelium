// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useRef, useState, type HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/** The blur at a cut-off edge: layers that blur harder toward the edge, each
 *  masked to fade in, so the rows soften progressively rather than at a line. */
const LAYERS = [
  { blur: 1, from: 0 },
  { blur: 3, from: 40 },
  { blur: 6, from: 70 },
];

function EdgeBlur({ edge }: { edge: "top" | "bottom" }) {
  // The mask runs from the list's inside toward the edge.
  const toward = edge === "bottom" ? "to bottom" : "to top";
  return (
    <div
      aria-hidden
      data-edge-blur={edge}
      className={cn("pointer-events-none absolute inset-x-0 h-8", edge === "bottom" ? "bottom-0" : "top-0")}
    >
      {LAYERS.map(({ blur, from }) => {
        const mask = `linear-gradient(${toward}, transparent ${from}%, black 100%)`;
        return (
          <div
            key={blur}
            className="absolute inset-0"
            style={{
              backdropFilter: `blur(${blur}px)`,
              WebkitBackdropFilter: `blur(${blur}px)`,
              maskImage: mask,
              WebkitMaskImage: mask,
            }}
          />
        );
      })}
    </div>
  );
}

/**
 * A vertically scrolling list whose cut-off edges blur, so a list with more
 * above or below it says so. An edge blurs only while there is something past
 * it: a list that fits shows none, and scrolling to the end clears that end.
 * `className` lays out the frame; everything else goes to the scrolling list.
 */
export function FadeScroll({ className, onScroll, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  const ref = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ top: false, bottom: false });

  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const top = el.scrollTop > 1;
    const bottom = el.scrollTop + el.clientHeight < el.scrollHeight - 1;
    setEdges((prev) => (prev.top === top && prev.bottom === bottom ? prev : { top, bottom }));
  }, []);

  // The list's own size changes with the rail, its content's with what it
  // holds (rows arriving, a folder opening); either can start or end overflow.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    measure();
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    resize?.observe(el);
    const mutate = typeof MutationObserver === "undefined" ? null : new MutationObserver(measure);
    mutate?.observe(el, { childList: true, subtree: true });
    return () => {
      resize?.disconnect();
      mutate?.disconnect();
    };
  }, [measure]);

  return (
    <div className={cn("relative flex min-h-0 flex-col", className)}>
      <div
        ref={ref}
        {...props}
        data-fade-top={edges.top || undefined}
        data-fade-bottom={edges.bottom || undefined}
        className="min-h-0 flex-1 overflow-y-auto"
        onScroll={(e) => {
          measure();
          onScroll?.(e);
        }}
      >
        {children}
      </div>
      {edges.top && <EdgeBlur edge="top" />}
      {edges.bottom && <EdgeBlur edge="bottom" />}
    </div>
  );
}
