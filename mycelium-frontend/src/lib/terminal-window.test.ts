// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { beforeEach, describe, expect, it } from "vitest";
import { MIN_WINDOW, clampRect, defaultRect, maxSize, saveRect, savedRect } from "@/lib/terminal-window";

const screen = { width: 1440, height: 900 };

describe("a popped-out terminal's place", () => {
  beforeEach(() => window.localStorage.clear());

  it("starts on the right, as tall as the room, between the title bar and the status bar", () => {
    const r = defaultRect(screen);
    expect(screen.width - (r.x + r.width)).toBeLessThanOrEqual(16);
    expect(r.y).toBeGreaterThan(0);
    expect(r.y + r.height).toBeLessThan(screen.height);
    expect(r.height).toBeGreaterThan(screen.height * 0.8);
  });

  it("stays wholly inside the window, wherever it's dragged or left", () => {
    const inside = (r: { x: number; y: number; width: number; height: number }) =>
      r.x >= 0 && r.y >= 0 && r.x + r.width <= screen.width && r.y + r.height <= screen.height;
    // Left on a bigger screen, or dragged past any edge.
    for (const [x, y] of [
      [2400, 1300],
      [-500, 100],
      [100, -50],
      [1400, 100],
      [100, 880],
    ]) {
      expect(inside(clampRect({ x, y, width: 640, height: 680 }, screen))).toBe(true);
    }
    // Dragged to the edge it keeps a small gap, and inside it isn't moved.
    expect(clampRect({ x: 2000, y: 0, width: 640, height: 680 }, screen)).toMatchObject({ x: 792, y: 8 });
    expect(clampRect({ x: 200, y: 100, width: 640, height: 680 }, screen)).toMatchObject({ x: 200, y: 100 });
  });

  it("grows from its corner only as far as the window's edge", () => {
    expect(maxSize({ x: 200, y: 100, width: 640, height: 680 }, screen)).toEqual({ width: 1232, height: 792 });
    // Never below the smallest it can be.
    expect(maxSize({ x: 1300, y: 800, width: 320, height: 240 }, screen)).toEqual(MIN_WINDOW);
  });

  it("keeps its top left on a window too small for it, so its header can be reached", () => {
    const r = clampRect({ x: 50, y: 50, width: 640, height: 680 }, { width: 300, height: 200 });
    expect(r).toMatchObject({ x: 8, y: 8, ...MIN_WINDOW });
  });

  it("is never bigger than the screen, or smaller than a few lines", () => {
    expect(clampRect({ x: 0, y: 0, width: 4000, height: 4000 }, screen)).toMatchObject({ width: 1424, height: 884 });
    expect(clampRect({ x: 0, y: 0, width: 10, height: 10 }, screen)).toMatchObject(MIN_WINDOW);
  });

  it("is remembered per agent, whatever the case of the handle", () => {
    expect(savedRect("builder")).toBeNull();
    saveRect("Builder", { x: 10, y: 20, width: 500, height: 600 });
    expect(savedRect("builder")).toEqual({ x: 10, y: 20, width: 500, height: 600 });
    expect(savedRect("reviewer")).toBeNull();
  });

  it("forgets a stored place that isn't one", () => {
    window.localStorage.setItem("mycelium.terminal-windows", JSON.stringify({ builder: { x: "left" } }));
    expect(savedRect("builder")).toBeNull();
  });
});
