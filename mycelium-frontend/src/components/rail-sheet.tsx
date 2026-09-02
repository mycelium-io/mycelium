// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, type ReactNode } from "react";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Which edge it comes in from — the edge the rail sits on when it's a panel. */
  side: "left" | "right";
  /** Accessible name for the sheet, since the rail inside it has no heading. */
  label: string;
  children: ReactNode;
}

/**
 * A rail, drawn over the workspace instead of beside it.
 *
 * On a window too narrow to hold a split, this is what the rooms rail and the
 * inspector become. It's the same rail — the components render exactly what
 * they render in a panel — moved out of the layout so opening one costs the
 * workspace nothing rather than costing it more width than it has.
 *
 * It keeps the strip visible underneath: the sheet stops short of the far edge
 * so the icon strip that opened it is still on screen, and tapping the strip's
 * own toggle closes it again.
 */
export function RailSheet({ open, onClose, side, label, children }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex" style={{ justifyContent: side === "left" ? "flex-start" : "flex-end" }}>
      <div
        className="absolute inset-0 bg-black/50 data-open:animate-in data-open:fade-in-0"
        data-open
        onClick={onClose}
        aria-hidden
      />
      <aside
        aria-label={label}
        data-open
        className={`relative flex h-full w-[min(20rem,calc(100vw-3rem))] flex-col bg-bg shadow-2xl data-open:animate-in ${
          side === "left"
            ? "ml-12 border-r border-border data-open:slide-in-from-left-4"
            : "mr-12 border-l border-border data-open:slide-in-from-right-4"
        }`}
      >
        {children}
      </aside>
    </div>
  );
}
