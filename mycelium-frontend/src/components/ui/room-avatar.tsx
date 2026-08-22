// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { cn } from "@/lib/utils";
import { avatarTint, initials } from "@/lib/avatar-color";

interface Props {
  name: string;
  /** The room currently open. Lifts the tile out of its resting state. */
  active?: boolean;
  /** Size and radius, e.g. "size-7 rounded-md". Defaults to a size-9 tile. */
  className?: string;
  children?: React.ReactNode;
}

/** A room's tile: its monogram over a gradient in the room's own stable colour.
 *
 *  Rooms are the thing you navigate between all day, so the tile is what you
 *  aim at — a column of identical grey squares makes you read every name first.
 *  The colour comes from the name, so it needs no storage and never drifts
 *  between the rail, the command centre and a card.
 *
 *  Decorative: the room name is always spelled beside or beneath it, so the
 *  tile is `aria-hidden` and adds nothing for a screen reader to re-read. */
export function RoomAvatar({ name, active = false, className, children }: Props) {
  const tint = avatarTint(name);
  return (
    <span
      aria-hidden
      className={cn(
        "relative flex size-9 flex-shrink-0 items-center justify-center rounded-lg border",
        "font-mono text-micro font-semibold transition-colors",
        className,
      )}
      // Opaque (mixed into `--paper`, not into transparency) so the tile keeps
      // its colour over a hover or selection highlight rather than tinting with
      // whatever is behind it.
      style={{
        background: `linear-gradient(135deg,
          color-mix(in srgb, ${tint} ${active ? 34 : 20}%, var(--paper)),
          color-mix(in srgb, ${tint} ${active ? 20 : 10}%, var(--paper)))`,
        borderColor: `color-mix(in srgb, ${tint} ${active ? 62 : 28}%, var(--paper))`,
        color: tint,
      }}
    >
      {initials(name)}
      {children}
    </span>
  );
}
