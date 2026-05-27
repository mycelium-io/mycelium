// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState, type ReactNode } from "react";

interface Props {
  label: string;
  children: ReactNode;
  expandedWidth?: number;
  collapsedWidth?: number;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function CollapsibleRail({
  label,
  children,
  expandedWidth = 420,
  collapsedWidth = 36,
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

  const labelLower = label.toLowerCase();

  return (
    <aside
      className="flex flex-shrink-0 border-l border-border bg-surface/40 overflow-hidden transition-[width] duration-200"
      style={{ width: open ? expandedWidth : collapsedWidth }}
    >
      <button
        onClick={toggle}
        className={`group w-9 flex-shrink-0 bg-paper hover:bg-accent/[0.08] transition-colors flex items-start justify-center pt-4 ${open ? "border-r border-border" : ""}`}
        aria-label={open ? `collapse ${labelLower}` : `expand ${labelLower}`}
      >
        <span
          className="caps-mono-sm text-muted group-hover:text-accent transition-colors"
          style={{ writingMode: "vertical-lr", letterSpacing: "0.2em" }}
        >
          {open ? `× ${label}` : label}
        </span>
      </button>
      {open && (
        <div className="flex-1 min-w-0 overflow-hidden">{children}</div>
      )}
    </aside>
  );
}
