// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useState } from "react";
import { SHEET_LAYOUT_WIDTH } from "@/lib/panel-layout";

/** How long the window has to hold still before anything acts on its width. A
 *  drag across a breakpoint is a stream of widths, and a layout measures itself
 *  against the one it has settled on, not the one mid-flight. */
export const SETTLE_MS = 150;

/** True while the settled window is narrower than `width`. Reports "wide" on
 *  the server and through hydration, then the real answer — which is also what
 *  makes a page loaded on a narrow window fold its rails on arrival. */
export function useNarrowerThan(width: number): boolean {
  const query = `(max-width: ${width - 1}px)`;
  const matches = useCallback(
    () => typeof window !== "undefined" && !!window.matchMedia && window.matchMedia(query).matches,
    [query],
  );
  const [narrow, setNarrow] = useState(matches);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const media = window.matchMedia(query);
    let settle = 0;
    const onChange = () => {
      clearTimeout(settle);
      settle = window.setTimeout(() => setNarrow(media.matches), SETTLE_MS);
    };
    setNarrow(media.matches);
    media.addEventListener("change", onChange);
    return () => {
      clearTimeout(settle);
      media.removeEventListener("change", onChange);
    };
  }, [query]);

  return narrow;
}

/**
 * True where the shell has stopped being a split: the rails are sheets over
 * the workspace rather than panels beside it, and the chrome that only makes
 * sense with a keyboard or a wide row has dropped out.
 *
 * One read, so every surface that changes shape on a phone changes at the same
 * width — and the same width the `sm`/`md` classes elsewhere use.
 */
export function useSheetLayout(): boolean {
  return useNarrowerThan(SHEET_LAYOUT_WIDTH);
}
