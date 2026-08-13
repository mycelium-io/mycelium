// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";

interface Props {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  /** Header actions (e.g. an Edit button), rendered before the close button. */
  actions?: ReactNode;
  children: ReactNode;
}

/** A right-side slide-over for reviewing/auditing a record (memory, episode)
 *  without leaving the workspace — the editor-native "open a file" gesture. */
export function DetailDrawer({ open, onClose, title, subtitle, actions, children }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-[1px] data-open:animate-in data-open:fade-in-0"
        data-open
        onClick={onClose}
        aria-hidden
      />
      <aside className="relative flex h-full w-[560px] max-w-[92vw] flex-col border-l border-border bg-elevated shadow-2xl data-open:animate-in data-open:slide-in-from-right-4" data-open>
        <header className="flex items-start gap-3 border-b border-border px-5 py-3.5">
          <div className="min-w-0 flex-1">
            <div className="truncate font-mono text-label font-semibold text-text">{title}</div>
            {subtitle && <div className="mt-0.5 text-micro text-muted-foreground">{subtitle}</div>}
          </div>
          {actions}
          <button
            onClick={onClose}
            aria-label="Close"
            className="flex size-7 flex-shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-text"
          >
            <X className="size-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </aside>
    </div>
  );
}
