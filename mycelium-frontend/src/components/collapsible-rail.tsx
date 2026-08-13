// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState, type ReactNode } from "react";
import { PanelRightClose, PanelRightOpen } from "lucide-react";

interface Props {
  label: string;
  children: ReactNode;
  expandedWidth?: number;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function CollapsibleRail({
  label,
  children,
  expandedWidth = 380,
  defaultOpen = false,
  open: openProp,
  onOpenChange,
}: Props) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isControlled = openProp !== undefined;
  const open = isControlled ? openProp : internalOpen;

  const toggle = () => {
    const next = !open;
    if (!isControlled) setInternalOpen(next);
    onOpenChange?.(next);
  };

  // Collapsed: a slim strip with a single, honestly-clickable toggle — no
  // rotated text, no 9px hit target.
  if (!open) {
    return (
      <aside className="flex w-12 flex-shrink-0 flex-col items-center border-l border-border bg-surface/40 pt-3">
        <button
          onClick={toggle}
          aria-label={`Open ${label.toLowerCase()}`}
          title={label}
          className="flex size-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-surface hover:text-text"
        >
          <PanelRightOpen className="size-[18px]" />
        </button>
      </aside>
    );
  }

  return (
    <aside
      className="flex flex-shrink-0 flex-col border-l border-border bg-surface/30"
      style={{ width: expandedWidth }}
    >
      <div className="flex h-[48px] flex-shrink-0 items-center gap-2 border-b border-border bg-paper px-4">
        <span className="text-label font-semibold text-text">{label}</span>
        <button
          onClick={toggle}
          aria-label={`Close ${label.toLowerCase()}`}
          className="ml-auto flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-text"
        >
          <PanelRightClose className="size-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
    </aside>
  );
}
