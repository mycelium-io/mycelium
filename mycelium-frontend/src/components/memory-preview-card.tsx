// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FileText } from "lucide-react";
import type { Memory } from "@/lib/api";
import { memoryPreview, previewCardTop } from "@/lib/memory-preview";

export const PREVIEW_CARD_WIDTH = 320; // px
const GAP = 10; // px between the card and the pane's left edge
const MARGIN = 12; // px kept clear of the viewport edges

export interface PreviewAnchor {
  /** Viewport rect of the hovered row. */
  top: number;
  height: number;
  /** Left edge of the whole memories pane — the card hangs off it, not the row,
   *  so it never covers the list it is previewing. */
  paneLeft: number;
}

interface Props {
  memory: Memory;
  anchor: PreviewAnchor;
}

function relativeTime(iso: string): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const min = Math.floor((Date.now() - t) / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.floor(hr / 24);
  if (d === 1) return "yesterday";
  if (d < 7) return `${d}d ago`;
  return new Date(iso).toISOString().slice(0, 10);
}

/** Hovercard for a memory row in the rail: a short excerpt of the body, parked
 *  to the left of the memories pane. */
export function MemoryPreviewCard({ memory, anchor }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState<number | null>(null);
  const [clipped, setClipped] = useState(false);
  const preview = memoryPreview(memory);

  // The excerpt's height is CSS's to decide, so whether it overflowed is read
  // off the laid-out element rather than predicted from the text. Both reads
  // happen before paint, so the card never shows a provisional state first.
  useLayoutEffect(() => {
    const el = ref.current;
    const body = bodyRef.current;
    if (!el) return;
    if (body) {
      const overflows = (n: Element) => n.scrollHeight > n.clientHeight + 1;
      setClipped(overflows(body) || Array.from(body.children).some(overflows));
    }
    setTop(
      previewCardTop(anchor.top, anchor.height, el.offsetHeight, window.innerHeight, MARGIN),
    );
  }, [anchor.top, anchor.height, memory.key]);

  if (typeof document === "undefined") return null;

  const left = Math.max(MARGIN, anchor.paneLeft - PREVIEW_CARD_WIDTH - GAP);
  const author = memory.updated_by || memory.created_by;
  const when = relativeTime(memory.updated_at);

  return createPortal(
    <div
      ref={ref}
      role="tooltip"
      data-testid="memory-preview-card"
      style={{
        position: "fixed",
        left,
        top: top ?? anchor.top,
        width: PREVIEW_CARD_WIDTH,
        visibility: top === null ? "hidden" : "visible",
      }}
      className="pointer-events-none z-50 animate-in fade-in-0 zoom-in-95 rounded-xl border border-border bg-elevated shadow-lg duration-100"
    >
      <div className="flex items-start gap-1.5 border-b border-border px-3 py-2">
        <FileText className="mt-px size-3.5 flex-shrink-0 text-faint" />
        <span className="min-w-0 flex-1 break-all font-mono text-label text-text">
          {memory.key}
        </span>
        {memory.key.startsWith("skills/") && (
          <span className="flex-shrink-0 rounded-sm border border-accent/30 bg-accent/10 px-1 text-[9px] font-medium leading-tight text-accent">
            skill
          </span>
        )}
      </div>

      {preview.empty ? (
        <p className="px-3 py-2 text-label italic text-faint">Empty memory</p>
      ) : (
        <div className="relative">
          {/* The excerpt's height is capped here, in CSS: `max-h` bounds the
              block and `line-clamp` bounds any one runaway paragraph, both in
              text units that follow the reader's font size. */}
          <div ref={bodyRef} className="max-h-52 space-y-1 overflow-hidden px-3 py-2">
            {preview.lines.map((line, i) => (
              <p
                key={i}
                className={`text-label leading-snug ${
                  line ? "line-clamp-4 break-words text-muted-foreground" : "h-1"
                }`}
              >
                {line}
              </p>
            ))}
          </div>
          {/* A cut excerpt fades out, so it reads as clipped rather than as a
              sentence that happens to stop. */}
          {(clipped || preview.truncated) && (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-elevated to-transparent" />
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 border-t border-border px-3 py-1.5 text-micro text-faint">
        <span className="tabular">v{memory.version}</span>
        {author && (
          <>
            <span>·</span>
            <span className="font-mono">{author}</span>
          </>
        )}
        {when && (
          <>
            <span>·</span>
            <span className="tabular">{when}</span>
          </>
        )}
        {(clipped || preview.truncated) && (
          <>
            <span>·</span>
            <span>more…</span>
          </>
        )}
        {memory.tags && memory.tags.length > 0 && (
          <span className="ml-auto flex flex-wrap gap-1">
            {memory.tags.slice(0, 3).map(tag => (
              <span
                key={tag}
                className="rounded-full border border-border bg-surface px-1.5 font-mono text-micro text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </span>
        )}
      </div>
    </div>,
    document.body,
  );
}
