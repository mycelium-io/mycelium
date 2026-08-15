// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { Mail } from "lucide-react";
import { cn } from "@/lib/utils";

/** Two-letter monogram from a handle: "backend-lead" → BL, "oc-test2" → OT,
 *  "main" → MA. Splits on non-alphanumerics, else first two chars. */
export function initials(handle: string): string {
  const parts = handle.split(/[^a-z0-9]+/i).filter(Boolean);
  const s =
    parts.length >= 2 ? parts[0][0] + parts[1][0] : (parts[0] ?? handle).slice(0, 2);
  return s.toUpperCase();
}

/** Live-presence tier. "slim" = active SLIM socket; "lease" = server-held
 *  await/reply poll; "herdr" = alive in a herdr pane (state from `status`). */
export type Presence = "slim" | "lease" | "herdr";

interface Props {
  handle: string;
  /** Glyph + tint color. Convention: accent for agents, muted for humans. */
  color?: string;
  /** Override the default size-8 circle (e.g. "size-5" for a compact chip). */
  className?: string;
  /** Optional live-presence, rendered as a colored halo ring + corner dot. */
  presence?: Presence;
  /** herdr live state (idle/working/blocked/done) — drives the halo color. */
  status?: string | null;
  /** A room mention queued for this handle, held until it goes idle — overlays a
   *  mail badge top-right. */
  wakePending?: boolean;
}

const HERDR_STATES = new Set(["idle", "working", "blocked", "done"]);

interface HaloSpec {
  color: string;
  /** Ring the avatar — dropped for resting states (idle) where it's just noise. */
  ring: boolean;
  /** Breathe the whole ring — reserved for genuinely active states. */
  pulse: boolean;
  title: string;
}

/** Presence → halo color + motion. Activity (working/blocked) and a polling lease
 *  breathe; steady states (done/connected) hold a static ring; idle drops the
 *  ring entirely (just the corner dot) — a resting state shouldn't shout. */
function haloSpec(presence: Presence, status?: string | null): HaloSpec {
  if (status && HERDR_STATES.has(status)) {
    switch (status) {
      case "working":
        return { color: "var(--warning, #d19a45)", ring: true, pulse: true, title: "working" };
      case "blocked":
        return { color: "var(--destructive, #d1495b)", ring: true, pulse: true, title: "blocked — needs input" };
      case "done":
        return { color: "var(--success, #4c9a6a)", ring: true, pulse: false, title: "done" };
      default: // idle — no ring, just the dot
        return { color: "var(--muted-foreground)", ring: false, pulse: false, title: "idle — asleep" };
    }
  }
  if (presence === "slim") return { color: "var(--accent)", ring: true, pulse: false, title: "connected" };
  if (presence === "lease") return { color: "var(--muted-foreground)", ring: true, pulse: true, title: "awaiting" };
  return { color: "var(--muted-foreground)", ring: false, pulse: false, title: "present" };
}

/** Circular initials avatar shared across the agent roster, event stream, and
 *  the acting-as picker so every handle renders the same way.
 *
 *  Presence is a **colored halo** ringing the avatar (state = color, activity =
 *  a breathing pulse) plus a small corner dot — calmer than an icon-in-a-badge,
 *  and the ring never bleeds the row line (it breathes via box-shadow, not
 *  opacity). A queued wake overlays a separate mail badge top-right. */
export function Monogram({ handle, color = "var(--accent)", className, presence, status, wakePending }: Props) {
  const halo = presence ? haloSpec(presence, status) : null;
  return (
    <div className="relative flex-shrink-0">
      <div
        aria-hidden
        title={halo?.title}
        className={cn(
          "flex size-8 items-center justify-center rounded-full font-mono text-micro font-semibold",
          halo?.ring && "avatar-halo",
          halo?.ring && halo.pulse && "pulse",
          className,
        )}
        style={{
          background: `color-mix(in srgb, ${color} 16%, transparent)`,
          color,
          ...(halo ? ({ "--halo": halo.color } as React.CSSProperties) : {}),
        }}
      >
        {initials(handle)}
      </div>
      {halo && <StateDot color={halo.color} />}
      {wakePending && <MailBadge />}
    </div>
  );
}

/** Small solid corner dot in the halo color — a definite "presence point" that
 *  reads even when the idle halo is subtle. Static (no opacity pulse — the halo
 *  carries the motion). */
function StateDot({ color }: { color: string }) {
  return (
    <span
      className="absolute bottom-0 right-0 block size-2 rounded-full ring-2 ring-paper"
      style={{ background: color }}
    />
  );
}

/** Top-right mail overlay: a queued mention held until the agent is idle. Sits
 *  opposite the state dot so "busy AND tagged" reads as both at once. */
function MailBadge() {
  return (
    <span
      className="absolute -top-0.5 -right-0.5 flex size-3.5 items-center justify-center rounded-full ring-2 ring-paper"
      style={{ background: "var(--accent)" }}
      title="wake queued — held until this agent is idle"
    >
      <Mail className="size-2.5" strokeWidth={2.75} style={{ color: "var(--paper)" }} />
    </span>
  );
}
