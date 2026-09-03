// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

/** The surface the region sits on, so the fade lands on the right color. */
const FADE = {
  bg: "var(--bg)",
  paper: "var(--paper)",
  surface: "var(--surface)",
  elevated: "var(--elevated)",
} as const;

/** Below this much overshoot, clamping would hide a line or two and cost a
 *  click to read them — worse than just showing the whole thing. */
const SLACK = 48;

interface Props {
  /** Height, in px, the region clamps to while collapsed. */
  collapsedHeight: number;
  /** The surface behind the region. */
  fade?: keyof typeof FADE;
  /** Names what expands, for the button's accessible label. */
  label?: string;
  children: ReactNode;
}

/**
 * A region that clamps itself when it is long, and only then.
 *
 * Keeps one scroll boundary for the whole column, the way an issue body
 * works: a fixed-height inner scrollbox would put a second scrollbar inside
 * the first, so the wheel does different things a few pixels apart.
 *
 * Content shorter than {@link Props.collapsedHeight} renders untouched, with no
 * button and no fade: nothing here appears until there is something to hide.
 */
export function Expandable({ collapsedHeight, fade = "bg", label, children }: Props) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  const [expanded, setExpanded] = useState(false);

  // Height is measured, not estimated from character count: the body renders
  // markdown, so height depends on rendering. Re-measures as images load and
  // the pane resizes.
  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const measure = () => setOverflows(el.scrollHeight > collapsedHeight + SLACK);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [collapsedHeight]);

  const clamped = overflows && !expanded;

  return (
    <div>
      <div
        ref={contentRef}
        className="relative"
        style={clamped ? { maxHeight: collapsedHeight, overflow: "hidden" } : undefined}
      >
        {children}
        {clamped && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 h-20"
            style={{ background: `linear-gradient(to top, ${FADE[fade]}, transparent)` }}
          />
        )}
      </div>
      {overflows && (
        <button
          type="button"
          onClick={() => setExpanded(v => !v)}
          aria-expanded={expanded}
          aria-label={label ? `${expanded ? "Collapse" : "Expand"} ${label}` : undefined}
          className="mt-1 inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2.5 py-1 text-micro font-medium text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
        >
          {expanded ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          {expanded ? "Collapse" : "Expand"}
        </button>
      )}
    </div>
  );
}
