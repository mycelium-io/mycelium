// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { Mail } from "lucide-react";
import { cn } from "@/lib/utils";
import { avatarTint, initials } from "@/lib/avatar-color";
import { Tooltip } from "@/components/ui/tooltip";

export { initials };

/** Live-presence tier surfaced as a halo around the avatar. "slim" = active
 *  SLIM socket (steady accent ring); "lease" = server-held await/reply poll
 *  (breathing muted ring); "herdr" = alive in a herdr pane, its ring color and
 *  motion driven by `status`. Undefined = not present, no halo. */
export type Presence = "slim" | "lease" | "herdr";

interface Props {
  handle: string;
  /** Glyph + tint. Defaults to the handle's own stable color; pass
   *  `var(--muted-foreground)` for a human, who stays neutral by convention. */
  color?: string;
  /** Override the default size-8 circle (e.g. "size-5" for a compact chip). */
  className?: string;
  /** Optional live-presence halo. */
  presence?: Presence;
  /** herdr live state (idle/working/blocked/done), which drives the halo color
   *  and motion for a herdr-hosted member. */
  status?: string | null;
  /** A room mention queued for this handle, held until it goes idle, overlaid as
   *  a mail badge in the top-right corner. */
  wakePending?: boolean;
  /** Drop the presence dot's own tooltip. Set where the avatar sits inside a
   *  larger hover target (a roster row's card, a facepile chip) that already
   *  names the presence, otherwise the dot's bubble intercepts that hover. */
  mutePresence?: boolean;
}

interface Halo {
  color: string;
  /** Breathe the ring — reserved for a poll that is genuinely mid-flight. */
  pulse: boolean;
  /** Ring the avatar. Dropped for a resting state (idle), where the corner dot
   *  carries presence on its own and a ring would only be noise. */
  ring: boolean;
  label: string;
}

const HERDR_STATES = new Set(["idle", "working", "blocked", "done"]);

/** Presence → ring color and motion. A herdr state colors the ring by activity
 *  (working/blocked breathe, done is a steady green, idle drops the ring); a held
 *  SLIM socket is a steady fact and holds a static ring; a lease is a poll in
 *  flight, so it breathes. */
function halo(presence: Presence, status?: string | null): Halo {
  if (presence === "herdr" || (status && HERDR_STATES.has(status))) {
    switch (status) {
      case "working":
        return { color: "var(--warning, #d19a45)", ring: true, pulse: true, label: "working" };
      case "blocked":
        return { color: "var(--destructive, #d1495b)", ring: true, pulse: true, label: "blocked, needs input" };
      case "done":
        return { color: "var(--success, #4c9a6a)", ring: true, pulse: false, label: "done" };
      default: // idle — no ring, just the dot
        return { color: "var(--muted-foreground)", ring: false, pulse: false, label: "idle, asleep" };
    }
  }
  return presence === "slim"
    ? { color: "var(--accent)", ring: true, pulse: false, label: "SLIM connected" }
    : { color: "var(--muted-foreground)", ring: true, pulse: true, label: "server-held lease (awaiting)" };
}

/** Circular monogram avatar; shared across roster, stream, and picker.
 *
 *  The disc is a solid fill in the handle's own color with near-white
 *  initials, so a roster reads as distinct people at a glance instead of a
 *  column of identical chips. Presence rides as a **halo** around it — color
 *  for the tier, a breathing ring for a poll in flight — plus a corner dot that
 *  carries the tier on its own for anyone the ring's color doesn't reach. */
export function Monogram({ handle, color, className, presence, status, wakePending, mutePresence }: Props) {
  const tint = color ?? avatarTint(handle);
  const ring = presence ? halo(presence, status) : null;
  return (
    <div className="relative flex-shrink-0">
      <div
        aria-hidden
        className={cn(
          "flex size-8 items-center justify-center rounded-full border font-mono text-micro font-semibold",
          ring?.ring && "avatar-halo",
          ring?.ring && ring.pulse && "pulse",
          className,
        )}
        // Opaque fill: the command center stacks these, and translucent discs
        // overlapping would blend into each other. Opaque also holds the
        // color steady over a hover highlight. Border is the same tint
        // darkened; glyph is white for contrast against the deep disc.
        style={{
          background: tint,
          borderColor: `color-mix(in srgb, ${tint} 70%, #000)`,
          color: "#fff",
          ...(ring ? ({ "--halo": ring.color } as React.CSSProperties) : {}),
        }}
      >
        {initials(handle)}
      </div>
      {ring && <PresenceDot halo={ring} mute={mutePresence} />}
      {wakePending && <MailBadge />}
    </div>
  );
}

/** Top-right mail overlay: a mention queued for this handle, held until the agent
 *  goes idle. Sits opposite the presence dot so "busy and tagged" reads as both. */
function MailBadge() {
  return (
    <Tooltip content="wake queued, held until this agent is idle">
      <span
        className="absolute -top-0.5 -right-0.5 flex size-3.5 items-center justify-center rounded-full ring-2 ring-paper"
        style={{ background: "var(--accent)" }}
      >
        <Mail className="size-2.5" strokeWidth={2.75} style={{ color: "var(--paper)" }} />
      </span>
    </Tooltip>
  );
}

/** The corner dot. The halo is a color, and color alone shouldn't be the only
 *  carrier of a tier, so the dot names itself for screen readers rather than
 *  leaning on the tooltip a pointer reveals. */
function PresenceDot({ halo: ring, mute }: { halo: Halo; mute?: boolean }) {
  const dot = (
    <span
      role="img"
      aria-label={ring.label}
      className="absolute -bottom-0.5 -right-0.5 block size-2.5 rounded-full ring-2 ring-paper"
      style={{ background: ring.color }}
    />
  );
  // Muted: keep the dot and its accessible name, drop the hover bubble so it does
  // not intercept an enclosing hover target.
  return mute ? dot : <Tooltip content={ring.label}>{dot}</Tooltip>;
}
