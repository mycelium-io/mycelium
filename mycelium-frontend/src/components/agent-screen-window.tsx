// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Where an agent's terminal opens: a window over the app that you drag by its
 * header and resize from its corner. Nothing behind it dims and a click
 * elsewhere doesn't close it, since you watch an agent while you read and
 * write in the room.
 *
 * The first time, it opens full height on the right, where Members is. After
 * that, each agent's opens where you last left it, put back on screen if the
 * window has shrunk since (`lib/terminal-window.ts`). Esc or × closes it.
 *
 *   {watching && <AgentScreenWindow room handle runner onClose />}
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { LayoutList, SquareTerminal, X } from "lucide-react";
import { AgentScreen, type AgentScreenProps, type ScreenView } from "@/components/agent-screen";
import { Monogram } from "@/components/ui/monogram";
import { Tooltip } from "@/components/ui/tooltip";
import { useAgentActivity } from "@/lib/agent-activity";
import { useIsDesktop } from "@/lib/desktop";
import { MIN_WINDOW, clampRect, defaultRect, saveRect, savedRect, type WindowRect } from "@/lib/terminal-window";
import { cn } from "@/lib/utils";

const viewport = () => ({ width: window.innerWidth, height: window.innerHeight });

const VIEWS = [
  { view: "rendered", label: "What it's doing", Icon: LayoutList },
  { view: "terminal", label: "Its terminal", Icon: SquareTerminal },
] as const;

/** The view last picked, for every agent's window. Rendered until one is. */
const VIEW_KEY = "mycelium.terminal-view";

function savedView(): ScreenView {
  try {
    return localStorage.getItem(VIEW_KEY) === "terminal" ? "terminal" : "rendered";
  } catch {
    return "rendered";
  }
}

function saveView(view: ScreenView): void {
  try {
    localStorage.setItem(VIEW_KEY, view);
  } catch {}
}

export function AgentScreenWindow({ onClose, ...props }: AgentScreenProps & { onClose: () => void }) {
  const { handle } = props;
  // It only ever opens from a click, so the window is there to measure.
  const [rect, setRect] = useState<WindowRect>(() => clampRect(savedRect(handle) ?? defaultRect(viewport()), viewport()));
  const section = useRef<HTMLElement | null>(null);
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  // The toggle shows only for an agent whose CLI the app can draw.
  const desktop = useIsDesktop();
  const { activity } = useAgentActivity(desktop ? { room: props.room, handle } : null);
  const rendered = activity !== null;
  const [view, setView] = useState<ScreenView>(savedView);
  const choose = (v: ScreenView) => {
    setView(v);
    saveView(v);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // A menu or dialog that took the Esc first keeps it.
      if (e.key === "Escape" && !e.defaultPrevented) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // A window that shrinks keeps the terminal on it.
  useEffect(() => {
    const onResize = () => setRect((r) => clampRect(r, viewport()));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Resizing from the corner is the browser's; what it settles on is kept.
  useEffect(() => {
    const el = section.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      const width = Math.round(el.offsetWidth);
      const height = Math.round(el.offsetHeight);
      setRect((r) => {
        if (r.width === width && r.height === height) return r;
        const next = { ...r, width, height };
        saveRect(handle, next);
        return next;
      });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [handle]);

  return createPortal(
    <section
      ref={section}
      aria-label={`@${handle}'s terminal`}
      className="fixed z-50 flex resize flex-col overflow-hidden rounded-xl border border-border2 bg-bg shadow-2xl motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-[0.98]"
      style={{
        left: rect.x,
        top: rect.y,
        width: rect.width,
        height: rect.height,
        minWidth: MIN_WINDOW.width,
        minHeight: MIN_WINDOW.height,
      }}
    >
      <header
        className="flex h-10 flex-none cursor-grab touch-none items-center gap-2 border-b border-border px-3 select-none active:cursor-grabbing"
        onPointerDown={(e) => {
          if ((e.target as HTMLElement).closest("button")) return;
          drag.current = { dx: e.clientX - rect.x, dy: e.clientY - rect.y };
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (!drag.current) return;
          setRect(clampRect({ ...rect, x: e.clientX - drag.current.dx, y: e.clientY - drag.current.dy }, viewport()));
        }}
        onPointerUp={() => {
          if (drag.current) saveRect(handle, rect);
          drag.current = null;
        }}
      >
        <Monogram handle={handle} kind="agent" className="size-5 text-[9px]" />
        <span className="truncate text-label font-medium text-text">@{handle}</span>
        <span className="truncate text-micro text-faint">{props.room}</span>
        {rendered && (
          <div role="radiogroup" aria-label="Show" className="ml-auto flex flex-none rounded-md border border-border p-0.5">
            {VIEWS.map(({ view: v, label, Icon }) => (
              <Tooltip key={v} content={label}>
                <button
                  type="button"
                  role="radio"
                  aria-checked={view === v}
                  aria-label={label}
                  onClick={() => choose(v)}
                  className={cn(
                    "grid size-6 place-items-center rounded text-muted-foreground hover:text-text",
                    view === v && "bg-hairline text-text",
                  )}
                >
                  <Icon className="size-3.5" />
                </button>
              </Tooltip>
            ))}
          </div>
        )}
        <button
          type="button"
          aria-label={`Close @${handle}'s terminal`}
          onClick={onClose}
          className={cn(
            "grid size-6 flex-none place-items-center rounded text-muted-foreground hover:bg-hairline hover:text-text",
            !rendered && "ml-auto",
          )}
        >
          <X className="size-3.5" />
        </button>
      </header>
      <AgentScreen {...props} view={rendered ? view : "terminal"} onView={choose} />
    </section>,
    document.body,
  );
}
