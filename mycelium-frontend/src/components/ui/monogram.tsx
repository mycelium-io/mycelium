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

/** Live-presence tier surfaced as a corner badge on the avatar. "slim" = active
 *  SLIM socket (solid accent); "lease" = server-held await/reply poll (pulsing
 *  muted); "herdr" = alive in a herdr pane but not joined (color by `status`).
 *  Undefined = not present, no badge. */
export type Presence = "slim" | "lease" | "herdr";

interface Props {
  handle: string;
  /** Glyph + tint color. Convention: accent for agents, muted for humans. */
  color?: string;
  /** Override the default size-8 circle (e.g. "size-5" for a compact chip). */
  className?: string;
  /** Optional live-presence badge in the bottom-right corner (chat-app style). */
  presence?: Presence;
  /** herdr live state (idle/working/blocked/done), colors the badge for `herdr`
   *  presence and augments a slim/lease member also alive in herdr. */
  status?: string | null;
}

/** Circular initials avatar shared across the agent roster, event stream, and
 *  the acting-as picker so every handle renders the same way. */
export function Monogram({ handle, color = "var(--accent)", className, presence, status }: Props) {
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
      {presence && <PresenceBadge presence={presence} status={status} />}
    </div>
  );
}

/** Per-herdr-state badge color + pulse + tooltip. `working`/`blocked` pulse to
 *  read as "needs attention / active"; `idle`/`done` are steady. */
function herdrBadge(status?: string | null): { color: string; pulse: boolean; title: string } {
  switch (status) {
    case "working":
      return { color: "var(--warning, #d19a45)", pulse: true, title: "herdr: working" };
    case "blocked":
      return { color: "var(--destructive, #d1495b)", pulse: true, title: "herdr: blocked (needs input)" };
    case "idle":
    case "done":
      return { color: "var(--success, #4c9a6a)", pulse: false, title: `herdr: ${status} (alive, not joined)` };
    default:
      return { color: "var(--muted-foreground)", pulse: false, title: `herdr: ${status ?? "unknown"}` };
  }
}

/** Corner presence dot, ringed by the panel background so it reads as an overlay
 *  on the avatar edge. Solid accent for a live socket, pulsing muted for a lease,
 *  status-colored for a herdr-only member. */
function PresenceBadge({ presence, status }: { presence: Presence; status?: string | null }) {
  let color = "var(--muted-foreground)";
  let pulse = presence !== "slim";
  let title = "server-held lease (awaiting)";
  if (presence === "slim") {
    color = "var(--accent)";
    title = "SLIM connected";
  } else if (presence === "herdr") {
    ({ color, pulse, title } = herdrBadge(status));
  }
  return (
    <span
      className={cn(
        "absolute -bottom-0.5 -right-0.5 block size-2.5 rounded-full ring-2 ring-paper",
        pulse && "animate-pulse",
      )}
      style={{ background: color }}
      title={title}
    />
  );
}
