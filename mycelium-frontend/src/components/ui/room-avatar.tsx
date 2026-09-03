// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { cn } from "@/lib/utils";
import { avatarTint, initials } from "@/lib/avatar-color";

interface Props {
  name: string;
  /** Size and radius, e.g. "size-7 rounded-md". Defaults to a size-9 tile. */
  className?: string;
  children?: React.ReactNode;
}

/** A room's tile: its monogram over a solid fill in the room's own stable colour.
 *
 *  Rooms are the thing you navigate between all day, so the tile is what you
 *  aim at — a column of identical grey squares makes you read every name first.
 *  The colour comes from the name, so it needs no storage and never drifts
 *  between the rail, the command centre and a card.
 *
 *  Selection is carried by the surrounding row (its own background + ring), not
 *  the tile, so the identity colour reads the same open or not.
 *
 *  Decorative: the room name is always spelled beside or beneath it, so the
 *  tile is `aria-hidden` and adds nothing for a screen reader to re-read. */
export function RoomAvatar({ name, className, children }: Props) {
  const tint = avatarTint(name);
  return (
    <span
      aria-hidden
      className={cn(
        "relative flex size-9 flex-shrink-0 items-center justify-center rounded-lg border",
        "font-mono text-micro font-semibold",
        className,
      )}
      // Opaque fill keeps the tile's colour stable over a hover or selection
      // highlight.
      style={{
        background: tint,
        borderColor: `color-mix(in srgb, ${tint} 70%, #000)`,
        color: "#fff",
      }}
    >
      {initials(name)}
      {children}
    </span>
  );
}
