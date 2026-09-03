// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useId, useState, type ReactElement, type ReactNode } from "react";
import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";

import { cn } from "@/lib/utils";

type Side = "top" | "bottom" | "left" | "right";
type Align = "start" | "center" | "end";

interface Props {
  /** Tooltip body. Nullish or empty renders the trigger bare, so a call site
   *  can keep passing a conditional label without branching on it. */
  content?: ReactNode;
  /** The element the tooltip describes; rendered as-is, not wrapped. */
  children: ReactElement;
  side?: Side;
  align?: Align;
  sideOffset?: number;
  className?: string;
}

/** Hover/focus tooltip in the app's own idiom — an elevated card on the
 *  surface ladder rather than the browser's OS-chrome `title` bubble.
 *
 *  The trigger is rendered through Base UI's `render` prop, so the child keeps
 *  its own tag, classes and refs; only tooltip wiring is merged in.
 *
 *  Base UI wires no ARIA of its own, so this does: the popup is a `tooltip`
 *  the open trigger points at, making the bubble the control's *description*
 *  the way `title` was. When the text is also the control's only name (an
 *  icon-only button, a bare glyph), the call site still supplies `aria-label`. */
export function Tooltip({
  content,
  children,
  side = "top",
  align = "center",
  sideOffset = 6,
  className,
}: Props) {
  const popupId = useId();
  const [open, setOpen] = useState(false);

  if (content === undefined || content === null || content === "") return children;

  return (
    <TooltipPrimitive.Root open={open} onOpenChange={setOpen}>
      {/* Only while the popup is mounted — a dangling id describes nothing. */}
      <TooltipPrimitive.Trigger
        render={children}
        aria-describedby={open ? popupId : undefined}
      />
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Positioner
          side={side}
          align={align}
          sideOffset={sideOffset}
          collisionPadding={8}
        >
          <TooltipPrimitive.Popup
            id={popupId}
            role="tooltip"
            data-slot="tooltip"
            className={cn(
              "z-50 max-w-64 origin-[var(--transform-origin)] rounded-md border border-border2",
              "bg-elevated px-2 py-1 text-micro leading-snug text-text shadow-lg outline-none",
              // Some content is a newline-joined list (an envelope's parents).
              "whitespace-pre-line",
              "duration-100 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95",
              "data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
              className,
            )}
          >
            {content}
          </TooltipPrimitive.Popup>
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

/** Shared open/close delay for every tooltip in the tree. Grouping means the
 *  first tooltip waits, then moving along a toolbar shows its neighbors
 *  immediately instead of re-waiting per control. */
export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <TooltipPrimitive.Provider delay={400} closeDelay={80}>
      {children}
    </TooltipPrimitive.Provider>
  );
}
