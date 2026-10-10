// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useRef, useState, type HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/** How far the fade reaches into the list from an edge with more beyond it. */
const FADE_PX = 24;

/** The mask for a list cut off above, below, both or neither. It fades into
 *  whatever the list sits on, so no surface color has to be named here. */
export function fadeMask(top: boolean, bottom: boolean): string | undefined {
  if (!top && !bottom) return undefined;
  const start = top ? `transparent, black ${FADE_PX}px` : "black";
  const end = bottom ? `black calc(100% - ${FADE_PX}px), transparent` : "black";
  return `linear-gradient(to bottom, ${start}, ${end})`;
}

/**
 * A vertically scrolling list whose cut-off edges fade out, so a list with
 * more above or below it says so. An edge fades only while there is something
 * past it: a list that fits shows none, and scrolling to the end clears that
 * end's fade.
 */
export function FadeScroll({ className, style, onScroll, children, ...props }: HTMLAttributes<HTMLDivElement>) {
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

  const mask = fadeMask(edges.top, edges.bottom);
  return (
    <div
      ref={ref}
      {...props}
      data-fade-top={edges.top || undefined}
      data-fade-bottom={edges.bottom || undefined}
      className={cn("overflow-y-auto", className)}
      style={mask ? { ...style, maskImage: mask, WebkitMaskImage: mask } : style}
      onScroll={(e) => {
        measure();
        onScroll?.(e);
      }}
    >
      {children}
    </div>
  );
}
