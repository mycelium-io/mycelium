// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { cn } from "@/lib/utils";
import { avatarTint, initials } from "@/lib/avatar-color";
import { Tooltip } from "@/components/ui/tooltip";

export { initials };

/** Live-presence tier surfaced as a halo around the avatar. "slim" = active
 *  SLIM socket (steady accent ring); "lease" = server-held await/reply poll
 *  (breathing muted ring). Undefined = not present, no halo. */
export type Presence = "slim" | "lease";

interface Props {
  handle: string;
  /** Glyph + tint. Defaults to the handle's own stable colour; pass
   *  `var(--muted-foreground)` for a human, who stays neutral by convention. */
  color?: string;
  /** Override the default size-8 circle (e.g. "size-5" for a compact chip). */
  className?: string;
  /** Optional live-presence halo. */
  presence?: Presence;
}

interface Halo {
  color: string;
  /** Breathe the ring — reserved for a poll that is genuinely mid-flight. */
  pulse: boolean;
  label: string;
}

/** Presence → ring colour and motion. A held socket is a steady fact and holds
 *  a static ring; a lease is a poll in flight, so it breathes. */
function halo(presence: Presence): Halo {
  return presence === "slim"
    ? { color: "var(--accent)", pulse: false, label: "SLIM connected" }
    : { color: "var(--muted-foreground)", pulse: true, label: "server-held lease (awaiting)" };
}

/** Circular monogram avatar; shared across roster, stream, and picker.
 *
 *  The disc is a soft gradient in the handle's own colour rather than a flat
 *  wash, so a roster reads as distinct people at a glance instead of a column
 *  of identical chips. Presence rides as a **halo** around it — colour for the
 *  tier, a breathing ring for a poll in flight — plus a corner dot that carries
 *  the tier on its own for anyone the ring's colour doesn't reach. */
export function Monogram({ handle, color, className, presence }: Props) {
  const tint = color ?? avatarTint(handle);
  const ring = presence ? halo(presence) : null;
  return (
    <div className="relative flex-shrink-0">
      <div
        aria-hidden
        className={cn(
          "flex size-8 items-center justify-center rounded-full border font-mono text-micro font-semibold",
          ring && "avatar-halo",
          ring?.pulse && "pulse",
          className,
        )}
        // Mixed into `--paper` rather than into transparency: the pile in the
        // command centre overlaps these, and translucent discs stacked on each
        // other turn to mud. Opaque also means the disc holds its colour over a
        // hover highlight instead of shifting with it.
        style={{
          background: `linear-gradient(140deg,
            color-mix(in srgb, ${tint} 20%, var(--paper)),
            color-mix(in srgb, ${tint} 11%, var(--paper)))`,
          borderColor: `color-mix(in srgb, ${tint} 30%, var(--paper))`,
          color: tint,
          ...(ring ? ({ "--halo": ring.color } as React.CSSProperties) : {}),
        }}
      >
        {initials(handle)}
      </div>
      {ring && <PresenceDot halo={ring} />}
    </div>
  );
}

/** The corner dot. The halo is a colour, and colour alone shouldn't be the only
 *  carrier of a tier, so the dot names itself for screen readers rather than
 *  leaning on the tooltip a pointer reveals. */
function PresenceDot({ halo: ring }: { halo: Halo }) {
  return (
    <Tooltip content={ring.label}>
      <span
        role="img"
        aria-label={ring.label}
        className="absolute -bottom-0.5 -right-0.5 block size-2.5 rounded-full ring-2 ring-paper"
        style={{ background: ring.color }}
      />
    </Tooltip>
  );
}
