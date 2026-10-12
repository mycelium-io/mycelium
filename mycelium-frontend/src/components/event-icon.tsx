// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { EventIcon } from "@/lib/event-icons";
import { cn } from "@/lib/utils";

/**
 * An event line's icon, in its color, sized to the line's text so a line
 * doesn't grow taller. It's labelled with what happened, for screen readers
 * and as a tooltip.
 */
export function EventIconMark({ icon, className }: { icon: EventIcon; className?: string }) {
  const { Icon, tone, label } = icon;
  return (
    <span role="img" aria-label={label} title={label} className={cn("inline-flex flex-shrink-0", className)}>
      <Icon aria-hidden className="size-3" strokeWidth={2.2} style={{ color: tone }} />
    </span>
  );
}
