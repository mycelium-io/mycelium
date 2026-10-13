// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { clippedTabs } from "@/components/room-dock";

/** A strip from `left` to `right`, with tabs at the given [left, right]s. */
function strip(left: number, right: number, tabs: Record<string, [number, number]>): Element {
  const box = (l: number, r: number) => () => ({ left: l, right: r, width: r - l }) as DOMRect;
  const el = document.createElement("div");
  el.getBoundingClientRect = box(left, right);
  for (const [id, [l, r]] of Object.entries(tabs)) {
    const tab = document.createElement("div");
    tab.dataset.panelId = id;
    tab.getBoundingClientRect = box(l, r);
    el.appendChild(tab);
  }
  return el;
}

describe("clippedTabs", () => {
  it("lists the tabs cut at either edge, in strip order", () => {
    const el = strip(100, 400, {
      before: [-20, 99],
      channel: [99.5, 200],
      stream: [200, 300],
      board: [300, 401],
      files: [401, 500],
    });
    expect(clippedTabs(el)).toEqual(["before", "files"]);
  });

  it("counts a tab wider than the strip as shown when its start is in view", () => {
    expect(clippedTabs(strip(100, 300, { long: [100, 340], next: [340, 420] }))).toEqual(["next"]);
    expect(clippedTabs(strip(100, 300, { long: [60, 300] }))).toEqual(["long"]);
  });

  it("lists nothing when every tab fits", () => {
    expect(clippedTabs(strip(0, 300, { a: [0, 100], b: [100, 200] }))).toEqual([]);
  });
});
