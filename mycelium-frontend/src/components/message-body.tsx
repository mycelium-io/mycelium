// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { MarkdownContent } from "@/components/markdown-content";
import type { Highlight } from "@/components/ui/highlight-text";

/** How tall a message's prose gets before it clamps behind a "Show more" —
 *  roughly eight lines of body text. Long enough that ordinary messages never
 *  clamp, short enough that a wall of text can't swallow the timeline. */
const CLAMP_PX = 168;

/**
 * A message's prose, clamped when it runs long.
 *
 * Both the room channel and a task's discussion are scannable logs, so one
 * message shouldn't be able to fill the viewport. Past ~eight lines the body is
 * capped with a soft fade and a muted "Show more" toggle; expanding is in place
 * and reversible, and nothing is summarized or thrown away — the reader still
 * gets every word on demand. Only the measured-too-tall case grows the control,
 * so short messages are untouched. Shared by the channel (`event-stream`) and
 * the thread pane (`task-conversation`) so the affordance is identical in both.
 */
export function MessageBody({
  content,
  hit,
  onOpenMemory,
}: {
  content: string;
  hit?: Highlight;
  onOpenMemory?: (key: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  const [expanded, setExpanded] = useState(false);

  // Measure the natural height (scrollHeight ignores the clamp) and re-measure on
  // width changes, since re-wrapping changes how tall the prose is.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") {
      if (el) setOverflows(el.scrollHeight > CLAMP_PX + 24);
      return;
    }
    const measure = () => setOverflows(el.scrollHeight > CLAMP_PX + 24);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [content]);

  // A find match forces the message open: the hit could be in the clamped-off
  // tail, and a highlight the reader can't see is a broken search. The manual
  // toggle steps aside while a match holds it open.
  const forceOpen = Boolean(hit);
  const clamped = overflows && !expanded && !forceOpen;

  return (
    <>
      <div
        ref={ref}
        className="relative overflow-hidden"
        style={clamped ? { maxHeight: CLAMP_PX } : undefined}
      >
        <MarkdownContent className="contrast text-body leading-relaxed" onLinkClick={onOpenMemory} highlight={hit}>
          {content}
        </MarkdownContent>
        {clamped && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-bg to-transparent" />
        )}
      </div>
      {overflows && !forceOpen && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 inline-flex items-center gap-0.5 text-micro font-medium text-muted-foreground transition-colors hover:text-text"
        >
          {expanded ? (
            <>Show less <ChevronUp className="size-3" /></>
          ) : (
            <>Show more <ChevronDown className="size-3" /></>
          )}
        </button>
      )}
    </>
  );
}
