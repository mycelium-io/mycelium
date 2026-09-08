// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  COLLAPSED_THRESHOLD_PX,
  INSPECTOR_FOLD_WIDTH,
  INSPECTOR_PANEL,
  MAIN_PANEL,
  ROOMS_FOLD_WIDTH,
  ROOMS_PANEL,
  TAB_LABELS_MIN_WIDTH,
  WORKSPACE_PANEL,
  SHEET_LAYOUT_WIDTH,
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
  // mean the labeled tabs clip at the floor and the icon strip never appears.
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

describe("folding a rail away", () => {
  // The whole reason the fold widths carry a margin. A group whose minimums no
  // longer fit refuses every resize, the collapse included — so each rail has
  // to fold while its window can still hold everything, not once it can't.
  it("folds the inspector while the room still fits around it", () => {
    const needed =
      px(ROOMS_PANEL.default) + px(MAIN_PANEL.min) + px(INSPECTOR_PANEL.min) + 2;
    expect(INSPECTOR_FOLD_WIDTH).toBeGreaterThan(needed);
  });

  it("folds the rooms rail while the window still fits it beside a chat", () => {
    const needed =
      px(ROOMS_PANEL.min) + px(MAIN_PANEL.min) + px(INSPECTOR_PANEL.collapsed) + 2;
    expect(ROOMS_FOLD_WIDTH).toBeGreaterThan(needed);
  });

  // One rail at a time, widest first: the inspector is the one a room can spare,
  // and folding it has to be enough on its own before the rooms rail goes too.
  it("folds the inspector before the rooms rail", () => {
    expect(ROOMS_FOLD_WIDTH).toBeLessThan(INSPECTOR_FOLD_WIDTH);
  });

  // Below the last fold, both strips plus chat still fit — the narrowest laid
  // out window is a readable one rather than a squeezed one.
  it("leaves room for chat between two folded strips", () => {
    const strips = px(ROOMS_PANEL.collapsed) + px(INSPECTOR_PANEL.collapsed) + 2;
    expect(strips + px(MAIN_PANEL.min)).toBeLessThan(ROOMS_FOLD_WIDTH);
  });

  // Both strips are read back through the same pixel threshold.
  it("reads both folded strips as collapsed", () => {
    expect(px(ROOMS_PANEL.collapsed)).toBeLessThan(COLLAPSED_THRESHOLD_PX);
    expect(px(INSPECTOR_PANEL.collapsed)).toBeLessThan(COLLAPSED_THRESHOLD_PX);
  });

  // The workspace's own minimum is part of the shell's constraint set at every
  // width, so it has to be satisfiable once the rooms rail is a strip.
  it("keeps the workspace's minimum satisfiable beside a folded rooms rail", () => {
    expect(px(ROOMS_PANEL.collapsed) + px(WORKSPACE_PANEL.min) + 1).toBeLessThan(
      ROOMS_FOLD_WIDTH,
    );
  });

  // The invariant the sheet layout exists for. A rail opened back into the
  // group needs its own default plus the workspace's floor plus the other
  // rail's strip, and a group handed constraints it cannot satisfy refuses to
  // move at all — which reads, to the reader who just tapped, as a rail that
  // does not open. So the sheet has to have taken over before that width, for
  // both rails.
  it("takes over before either rail stops fitting as a panel", () => {
    const roomsAsPanel =
      px(ROOMS_PANEL.default) + px(MAIN_PANEL.min) + px(INSPECTOR_PANEL.collapsed) + 2;
    const inspectorAsPanel =
      px(ROOMS_PANEL.collapsed) + px(MAIN_PANEL.min) + px(INSPECTOR_PANEL.default) + 2;
    expect(SHEET_LAYOUT_WIDTH).toBeGreaterThanOrEqual(roomsAsPanel);
    expect(SHEET_LAYOUT_WIDTH).toBeGreaterThanOrEqual(inspectorAsPanel);
  });

  // Tailwind's `md`. The layout switch and the classes that drop chrome at the
  // same width are two halves of one breakpoint, and a surface that changed
  // shape at one of them and not the other is the crowding this fixed.
  it("matches the breakpoint the classes use", () => {
    expect(SHEET_LAYOUT_WIDTH).toBe(768);
  });
});
