// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Where an agent's terminal opens: a window over the app that you drag by its
 * header and resize from any edge or corner. Nothing behind it dims and a click
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
import { useAgentSession } from "@/lib/agent-session";
import { useIsDesktop } from "@/lib/desktop";
import {
  clampRect,
  defaultRect,
  resizeRect,
  saveRect,
  savedRect,
  type Edge,
  type WindowRect,
} from "@/lib/terminal-window";
import { cn } from "@/lib/utils";

const viewport = () => ({ width: window.innerWidth, height: window.innerHeight });

/** Where each edge and corner can be grabbed, and the cursor it shows. The
 *  corners sit over the edges' ends, so a corner wins there. */
const EDGES: { edge: Edge; className: string }[] = [
  { edge: "n", className: "inset-x-0 top-0 h-1.5 cursor-ns-resize" },
  { edge: "s", className: "inset-x-0 bottom-0 h-1.5 cursor-ns-resize" },
  { edge: "w", className: "inset-y-0 left-0 w-1.5 cursor-ew-resize" },
  { edge: "e", className: "inset-y-0 right-0 w-1.5 cursor-ew-resize" },
  { edge: "nw", className: "left-0 top-0 size-3 cursor-nwse-resize" },
  { edge: "se", className: "bottom-0 right-0 size-3 cursor-nwse-resize" },
  { edge: "ne", className: "right-0 top-0 size-3 cursor-nesw-resize" },
  { edge: "sw", className: "bottom-0 left-0 size-3 cursor-nesw-resize" },
];

const VIEWS = [
  { view: "rendered", label: "What it's doing", Icon: LayoutList },
  { view: "terminal", label: "Terminal", Icon: SquareTerminal },
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
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  const resizing = useRef<{ edge: Edge; x: number; y: number; from: WindowRect } | null>(null);
  // The toggle shows once the app has answered for the agent, with its session
  // or why it has none. With none, the window opens on the terminal, whatever
  // was picked last; picking Rendered here then says why.
  const desktop = useIsDesktop();
  const read = useAgentSession(desktop ? { room: props.room, handle } : null);
  const rendered = read.session !== null || read.unavailable !== null;
  const [view, setView] = useState<ScreenView>(savedView);
  const [pickedHere, setPickedHere] = useState(false);
  const shown: ScreenView = read.unavailable && !pickedHere ? "terminal" : view;
  const choose = (v: ScreenView) => {
    setView(v);
    setPickedHere(true);
    // A pick made for an agent with nothing to draw doesn't change the others.
    if (!read.unavailable) saveView(v);
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

  return createPortal(
    <section
      aria-label={`@${handle}'s terminal`}
      className="fixed z-50 flex flex-col overflow-hidden rounded-xl border border-border2 bg-bg shadow-2xl motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-[0.98]"
      style={{ left: rect.x, top: rect.y, width: rect.width, height: rect.height }}
    >
      {EDGES.map(({ edge, className }) => (
        <div
          key={edge}
          aria-hidden
          data-edge={edge}
          className={cn("absolute z-10 touch-none", className)}
          onPointerDown={(e) => {
            resizing.current = { edge, x: e.clientX, y: e.clientY, from: rect };
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            const r = resizing.current;
            if (!r) return;
            setRect(resizeRect(r.from, r.edge, e.clientX - r.x, e.clientY - r.y, viewport()));
          }}
          onPointerUp={() => {
            if (resizing.current) saveRect(handle, rect);
            resizing.current = null;
          }}
        />
      ))}
      <header
        className="flex h-10 flex-none cursor-grab touch-none items-center gap-2 border-b border-border px-3 transition-colors select-none hover:bg-surface active:cursor-grabbing"
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
                  aria-checked={shown === v}
                  aria-label={label}
                  onClick={() => choose(v)}
                  className={cn(
                    "grid size-6 place-items-center rounded text-muted-foreground hover:text-text",
                    shown === v && "bg-hairline text-text",
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
      <AgentScreen {...props} view={rendered ? shown : "terminal"} onView={choose} />
    </section>,
    document.body,
  );
}
