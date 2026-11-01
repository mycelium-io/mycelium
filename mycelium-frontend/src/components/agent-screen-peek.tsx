// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Where an agent's terminal opens: a peek, a full-height card over the
 * workspace's right side, where Members is. Nothing behind it dims and a click
 * elsewhere doesn't close it, since you watch an agent while you read and
 * write in the room. A terminal is tall, so the peek is too.
 *
 * Pop out turns it into a window you drag by its header and resize from its
 * corner. It opens where that agent's window was last left, put back on screen
 * if the window has shrunk since (`lib/terminal-window.ts`). The same button
 * docks it again, and Esc closes it either way.
 *
 *   {watching && <AgentScreenPeek room handle runner onClose />}
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { PanelRight, PictureInPicture2, X } from "lucide-react";
import { AgentScreen, type AgentScreenProps } from "@/components/agent-screen";
import { Monogram } from "@/components/ui/monogram";
import { Tooltip } from "@/components/ui/tooltip";
import {
  MIN_WINDOW,
  PEEK_LAYER_ID,
  clampRect,
  defaultRect,
  saveRect,
  savedRect,
  type WindowRect,
} from "@/lib/terminal-window";
import { cn } from "@/lib/utils";
import { useIsClient } from "@/lib/client-hooks";

const viewport = () => ({ width: window.innerWidth, height: window.innerHeight });

export function AgentScreenPeek({ onClose, ...props }: AgentScreenProps & { onClose: () => void }) {
  const { handle } = props;
  // Null while it peeks; the window's place once popped out.
  const [rect, setRect] = useState<WindowRect | null>(null);
  const mounted = useIsClient();
  const [layer, setLayer] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the layer is on the page only once it has committed
    setLayer(document.getElementById(PEEK_LAYER_ID));
  }, []);
  const section = useRef<HTMLElement | null>(null);
  const drag = useRef<{ dx: number; dy: number } | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // A menu or dialog that took the Esc first keeps it.
      if (e.key === "Escape" && !e.defaultPrevented) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const place = useCallback(
    (next: WindowRect) => {
      const fitted = clampRect(next, viewport());
      setRect(fitted);
      saveRect(handle, fitted);
    },
    [handle],
  );

  // A window that shrinks keeps the terminal on it.
  const floating = rect !== null;
  useEffect(() => {
    if (!floating) return;
    const onResize = () => setRect((r) => (r ? clampRect(r, viewport()) : r));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [floating]);

  // Resizing from the corner is the browser's; what it settles on is kept.
  useEffect(() => {
    const el = section.current;
    if (!floating || !el) return;
    const observer = new ResizeObserver(() => {
      const width = Math.round(el.offsetWidth);
      const height = Math.round(el.offsetHeight);
      setRect((r) => {
        if (!r || (r.width === width && r.height === height)) return r;
        const next = { ...r, width, height };
        saveRect(handle, next);
        return next;
      });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [floating, handle]);

  const popOut = () => place(savedRect(handle) ?? defaultRect(viewport()));

  const header = (
    <header
      className={cn(
        "flex h-10 flex-none items-center gap-2 border-b border-border px-3",
        floating && "cursor-grab touch-none select-none active:cursor-grabbing",
      )}
      onPointerDown={(e) => {
        if (!rect || (e.target as HTMLElement).closest("button")) return;
        drag.current = { dx: e.clientX - rect.x, dy: e.clientY - rect.y };
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (!drag.current || !rect) return;
        setRect(clampRect({ ...rect, x: e.clientX - drag.current.dx, y: e.clientY - drag.current.dy }, viewport()));
      }}
      onPointerUp={() => {
        if (drag.current && rect) saveRect(handle, rect);
        drag.current = null;
      }}
    >
      <Monogram handle={handle} kind="agent" className="size-5 text-[9px]" />
      <span className="truncate text-label font-medium text-text">@{handle}</span>
      <span className="truncate text-micro text-faint">{props.room}</span>
      <Tooltip content={floating ? "Dock" : "Pop out"}>
        <button
          type="button"
          aria-label={floating ? `Dock @${handle}'s terminal` : `Pop out @${handle}'s terminal`}
          onClick={() => (floating ? setRect(null) : popOut())}
          className="ml-auto grid size-6 flex-none place-items-center rounded text-muted-foreground hover:bg-hairline hover:text-text"
        >
          {floating ? <PanelRight className="size-3.5" /> : <PictureInPicture2 className="size-3.5" />}
        </button>
      </Tooltip>
      <button
        type="button"
        aria-label={`Close @${handle}'s terminal`}
        onClick={onClose}
        className="grid size-6 flex-none place-items-center rounded text-muted-foreground hover:bg-hairline hover:text-text"
      >
        <X className="size-3.5" />
      </button>
    </header>
  );

  const card = (
    <section
      ref={section}
      aria-label={`@${handle}'s terminal`}
      className={cn(
        "pointer-events-auto flex flex-col overflow-hidden rounded-xl border border-border2 bg-bg shadow-2xl",
        floating
          ? "fixed z-50 resize"
          : cn(
              layer ? "absolute inset-y-2 right-2" : "fixed inset-y-12 right-2 z-40",
              "w-[min(600px,calc(100%-1rem))] motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-right-4",
            ),
      )}
      style={
        rect
          ? { left: rect.x, top: rect.y, width: rect.width, height: rect.height, minWidth: MIN_WINDOW.width, minHeight: MIN_WINDOW.height }
          : undefined
      }
    >
      {header}
      <AgentScreen {...props} />
    </section>
  );

  // Popped out, it's above everything; peeking, it's over the workspace only.
  const target = floating && mounted ? document.body : layer;
  return target ? createPortal(card, target) : card;
}
