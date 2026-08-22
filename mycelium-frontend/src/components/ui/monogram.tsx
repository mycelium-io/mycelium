// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { cn } from "@/lib/utils";
import { Tooltip } from "@/components/ui/tooltip";

/** Two-letter monogram from a handle: "backend-lead" → BL, "oc-test2" → OT,
 *  "main" → MA. Splits on non-alphanumerics, else first two chars. */
export function initials(handle: string): string {
  const parts = handle.split(/[^a-z0-9]+/i).filter(Boolean);
  const s =
    parts.length >= 2 ? parts[0][0] + parts[1][0] : (parts[0] ?? handle).slice(0, 2);
  return s.toUpperCase();
}

/** Live-presence tier surfaced as a corner badge on the avatar. "slim" = active
 *  SLIM socket (solid accent); "lease" = server-held await/reply poll (pulsing
 *  muted). Undefined = not present, no badge. */
export type Presence = "slim" | "lease";

interface Props {
  handle: string;
  /** Glyph + tint color. Convention: accent for agents, muted for humans. */
  color?: string;
  /** Override the default size-8 circle (e.g. "size-5" for a compact chip). */
  className?: string;
  /** Optional live-presence badge in the bottom-right corner (chat-app style). */
  presence?: Presence;
}

/** Circular initials avatar; shared across roster, stream, and picker. */
export function Monogram({ handle, color = "var(--accent)", className, presence }: Props) {
  return (
    <div className="relative flex-shrink-0">
      <div
        aria-hidden
        className={cn(
          "flex size-8 items-center justify-center rounded-full font-mono text-micro font-semibold",
          className,
        )}
        style={{ background: `color-mix(in srgb, ${color} 16%, transparent)`, color }}
      >
        {initials(handle)}
      </div>
      {presence && <PresenceBadge presence={presence} />}
    </div>
  );
}

/** Presence badge: solid for live socket, pulsing for server lease. The dot is
 *  the only carrier of the tier, so it names itself for screen readers rather
 *  than leaning on the tooltip a pointer reveals. */
function PresenceBadge({ presence }: { presence: Presence }) {
  const slim = presence === "slim";
  const label = slim ? "SLIM connected" : "server-held lease (awaiting)";
  return (
    <Tooltip content={label}>
      <span
        role="img"
        aria-label={label}
        className={cn(
          "absolute -bottom-0.5 -right-0.5 block size-2.5 rounded-full ring-2 ring-paper",
          !slim && "animate-pulse",
        )}
        style={{ background: slim ? "var(--accent)" : "var(--muted-foreground)" }}
      />
    </Tooltip>
  );
}
