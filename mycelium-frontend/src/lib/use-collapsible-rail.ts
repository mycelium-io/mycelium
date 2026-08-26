// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { usePanelRef, type PanelImperativeHandle, type PanelSize } from "react-resizable-panels";
import { COLLAPSED_THRESHOLD_PX } from "@/lib/panel-layout";
import { useNarrowerThan } from "@/lib/use-viewport";

interface Options {
  /** Viewport width below which the rail folds itself away. */
  foldWidth: number;
  /** The width the rail mounts at before anyone has dragged it. */
  defaultWidth: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface Rail {
  /** Hand to the rail's `<ResizablePanel panelRef=…>`. */
  panelRef: RefObject<PanelImperativeHandle | null>;
  /**
   * Hand to the rail's `<ResizablePanel defaultSize=…>` — the width it comes
   * back at, which is the width it left at.
   */
  size: string;
  /** Hand to the same panel's `onResize`. */
  onResize: (size: PanelSize) => void;
}

/**
 * A rail that folds itself away when the window gets too narrow to hold it.
 *
 * Folding is all it does. A window that grows again leaves the rails where they
 * are: which rails are open is the reader's call, and a window that grew is not
 * them asking for one back. The strip puts any of them back in a click, at the
 * width it left at.
 *
 * One state, three ways in — the reader, a drag past the minimum, and the
 * window — and each of them leaves the other two agreeing.
 */
export function useCollapsibleRail({
  foldWidth,
  defaultWidth,
  open,
  onOpenChange,
}: Options): Rail {
  const narrow = useNarrowerThan(foldWidth);

  // The width the rail was last at while open. The ref follows every drag; the
  // state is read at mount, so it only has to be current by the time the rail
  // is on its way back.
  const width = useRef(defaultWidth);
  const [mountWidth, setMountWidth] = useState(defaultWidth);
  const panelRef = usePanelRef();

  // However it went away — the window, the button, the keybind, a drag past the
  // minimum — the width it comes back at is the one it went away from.
  useEffect(() => {
    if (!open) setMountWidth(width.current);
  }, [open]);

  // Mounting the rail asks for that width; this is what makes the group give
  // it. A group stops tracking its own size while it holds a single panel, so
  // the rail it hands back is measured against however wide the window was when
  // the rail folded away. One resize on a settled window puts it right — and is
  // a no-op when the group got it right on its own.
  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel) return;
    const wanted = Number.parseInt(mountWidth, 10);
    // Next frame, not this one: a panel that has only just registered has no
    // layout in the group yet, and asking it to resize before it does throws.
    const frame = requestAnimationFrame(() => {
      if (Math.abs(panel.getSize().inPixels - wanted) > 1) panel.resize(`${wanted}px`);
    });
    return () => cancelAnimationFrame(frame);
  }, [mountWidth, open, panelRef]);

  // Panel → state: a drag past the minimum is how the rail is closed by hand,
  // and the panel reports it the same way it reports every other width.
  const onResize = useCallback(
    (size: PanelSize) => {
      if (size.inPixels <= COLLAPSED_THRESHOLD_PX) {
        if (open) onOpenChange(false);
        return;
      }
      // Only while the window can still hold the rail. Between the window
      // crossing the fold and the fold settling, the rail reports the widths a
      // group too small for it is squeezing it into — and those are the group
      // making do, not a width the reader chose.
      if (window.innerWidth >= foldWidth) width.current = `${Math.round(size.inPixels)}px`;
    },
    [foldWidth, open, onOpenChange],
  );

  // Read when the window crosses the fold, rather than resubscribing per toggle.
  const latest = useRef({ open, onOpenChange });
  useEffect(() => {
    latest.current = { open, onOpenChange };
  });

  // Only the crossing folds, and only ever in the one direction. Widening the
  // window doesn't unfold a rail: which rails are open is the reader's, and a
  // window that grew is not them asking for one back. It stays a click away in
  // the strip, where they left it.
  const folded = useRef(false);
  useEffect(() => {
    if (!narrow || folded.current) {
      folded.current = narrow;
      return;
    }
    folded.current = true;
    if (latest.current.open) latest.current.onOpenChange(false);
  }, [narrow]);

  return { panelRef, size: mountWidth, onResize };
}
