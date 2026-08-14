// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { cn } from "@/lib/utils";

/** Two-letter monogram from a handle: "backend-lead" → BL, "oc-test2" → OT,
 *  "main" → MA. Splits on non-alphanumerics, else first two chars. */
export function initials(handle: string): string {
  const parts = handle.split(/[^a-z0-9]+/i).filter(Boolean);
  const s =
    parts.length >= 2 ? parts[0][0] + parts[1][0] : (parts[0] ?? handle).slice(0, 2);
  return s.toUpperCase();
}

interface Props {
  handle: string;
  /** Glyph + tint color. Convention: accent for agents, muted for humans. */
  color?: string;
  /** Override the default size-8 circle (e.g. "size-5" for a compact chip). */
  className?: string;
}

/** Circular initials avatar shared across the agent roster, event stream, and
 *  the acting-as picker so every handle renders the same way. */
export function Monogram({ handle, color = "var(--accent)", className }: Props) {
  return (
    <div
      aria-hidden
      className={cn(
        "flex size-8 flex-shrink-0 items-center justify-center rounded-full font-mono text-micro font-semibold",
        className,
      )}
      style={{ background: `color-mix(in srgb, ${color} 16%, transparent)`, color }}
    >
      {initials(handle)}
    </div>
  );
}
