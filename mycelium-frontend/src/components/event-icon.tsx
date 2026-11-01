// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { EventIcon } from "@/lib/event-icons";
import { cn } from "@/lib/utils";

/**
 * An event line's icon, in its color, sized to the line's text so a line
 * doesn't grow taller. It's labelled with what happened, for screen readers
 * and as a tooltip.
 */
export function EventIconMark({
  icon,
  tone,
  className,
}: {
  icon: EventIcon;
  /** A color to draw it in instead of its own: the Stream colors an icon by
   *  the thread it belongs to, where the chat colors it by what happened. */
  tone?: string;
  className?: string;
}) {
  const { Icon, label } = icon;
  return (
    <span role="img" aria-label={label} title={label} className={cn("inline-flex flex-shrink-0", className)}>
      <Icon aria-hidden className="size-3" strokeWidth={2.2} style={{ color: tone ?? icon.tone }} />
    </span>
  );
}
