// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import * as ResizablePrimitive from "react-resizable-panels";

import { cn } from "@/lib/utils";

function ResizablePanelGroup({ className, ...props }: ResizablePrimitive.GroupProps) {
  return (
    <ResizablePrimitive.Group
      data-slot="resizable-panel-group"
      className={cn("flex h-full w-full aria-[orientation=vertical]:flex-col", className)}
      {...props}
    />
  );
}

/** A panel with `overflow: hidden`, centrally overriding the library's inline
 *  `overflow: auto` (which a utility class cannot beat) — every panel in this
 *  app scrolls inside its own body. Pass `style` to opt back in. */
function ResizablePanel({ style, ...props }: ResizablePrimitive.PanelProps) {
  return (
    <ResizablePrimitive.Panel
      data-slot="resizable-panel"
      style={{ overflow: "hidden", ...style }}
      {...props}
    />
  );
}

/** The draggable seam. It doubles as the border between two panes, so it draws
 *  the hairline the panels no longer draw themselves. The hit target is wider
 *  than the line (the `after:` overlay) so a 1px rule is still grabbable, and
 *  double-clicking it resets the neighbouring panel to its default size. */
function ResizableHandle({
  withHandle,
  className,
  ...props
}: ResizablePrimitive.SeparatorProps & { withHandle?: boolean }) {
  return (
    <ResizablePrimitive.Separator
      data-slot="resizable-handle"
      className={cn(
        "group/handle relative flex w-px items-center justify-center bg-border outline-none transition-colors",
        "after:absolute after:inset-y-0 after:left-1/2 after:w-3 after:-translate-x-1/2 after:content-['']",
        "data-[separator=hover]:bg-accent data-[separator=active]:bg-accent data-[separator=focus]:bg-accent",
        "aria-[orientation=horizontal]:h-px aria-[orientation=horizontal]:w-full",
        "aria-[orientation=horizontal]:after:inset-x-0 aria-[orientation=horizontal]:after:left-0",
        "aria-[orientation=horizontal]:after:h-3 aria-[orientation=horizontal]:after:w-full",
        "aria-[orientation=horizontal]:after:translate-x-0 aria-[orientation=horizontal]:after:-translate-y-1/2",
        "[&[aria-orientation=horizontal]>div]:rotate-90",
        className,
      )}
      {...props}
    >
      {withHandle && (
        <div
          className={cn(
            "z-10 h-8 w-1 shrink-0 rounded-full bg-border2 opacity-0 transition-opacity",
            "group-data-[separator=hover]/handle:opacity-100 group-data-[separator=focus]/handle:opacity-100",
            "group-data-[separator=active]/handle:bg-accent group-data-[separator=active]/handle:opacity-100",
          )}
        />
      )}
    </ResizablePrimitive.Separator>
  );
}

export { ResizableHandle, ResizablePanel, ResizablePanelGroup };
