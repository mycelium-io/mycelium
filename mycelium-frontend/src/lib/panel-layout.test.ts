// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  COLLAPSED_THRESHOLD_PX,
  INSPECTOR_PANEL,
  ROOMS_PANEL,
  TAB_LABELS_MIN_WIDTH,
} from "@/lib/panel-layout";

const px = (value: string) => Number.parseInt(value, 10);

describe("panel sizing", () => {
  it.each([
    ["rooms rail", ROOMS_PANEL],
    ["inspector rail", INSPECTOR_PANEL],
  ])("gives the %s a default inside its own bounds", (_name, panel) => {
    expect(px(panel.min)).toBeLessThan(px(panel.default));
    expect(px(panel.default)).toBeLessThan(px(panel.max));
  });

  // The whole point of the compact tab strip: it has to engage somewhere the
  // rail can actually be dragged to. A threshold at or below the minimum would
  // mean the labelled tabs clip at the floor and the icon strip never appears.
  it("drops the inspector's tab labels above its minimum width", () => {
    expect(TAB_LABELS_MIN_WIDTH).toBeGreaterThan(px(INSPECTOR_PANEL.min));
    expect(TAB_LABELS_MIN_WIDTH).toBeLessThan(px(INSPECTOR_PANEL.default));
  });

  // "Collapsed" is read off a pixel width, so the strip must be unambiguously
  // under the threshold and the minimum unambiguously over it.
  it("separates the collapsed strip from the smallest open rail", () => {
    expect(px(INSPECTOR_PANEL.collapsed)).toBeLessThan(COLLAPSED_THRESHOLD_PX);
    expect(COLLAPSED_THRESHOLD_PX).toBeLessThan(px(INSPECTOR_PANEL.min));
  });
});
