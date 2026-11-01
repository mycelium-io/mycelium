// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";

/**
 * Lay out a scroll element the way a browser would, for a test: a `view`-tall
 * window over content whose height is `rowHeight` per row matching `rows`, so
 * a reply landing makes the list taller. jsdom lays nothing out, so without
 * this every list is zero pixels tall and always at its bottom.
 */
export function layOut(el: HTMLElement, rows: string, { rowHeight = 500, view = 400 } = {}) {
  let top = 0;
  const height = () => Math.max(view, el.querySelectorAll(rows).length * rowHeight);
  const clamp = (v: number) => Math.max(0, Math.min(v, height() - view));
  Object.defineProperty(el, "scrollHeight", { configurable: true, get: height });
  Object.defineProperty(el, "clientHeight", { configurable: true, value: view });
  Object.defineProperty(el, "scrollTop", {
    configurable: true,
    get: () => top,
    set: (v: number) => {
      top = clamp(v);
    },
  });
  el.scrollTo = ((options: ScrollToOptions) => {
    el.scrollTop = Number(options.top);
  }) as typeof el.scrollTo;
  return {
    /** Whether the newest row is in view. */
    atBottom: () => top >= height() - view,
    /** The reader scrolls to `to`. */
    scrollTo: (to: number) =>
      act(() => {
        el.scrollTop = to;
        el.dispatchEvent(new Event("scroll"));
      }),
    top: () => top,
  };
}
