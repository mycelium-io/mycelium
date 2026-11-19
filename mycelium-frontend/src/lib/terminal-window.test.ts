// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { beforeEach, describe, expect, it } from "vitest";
import { MIN_WINDOW, clampRect, defaultRect, resizeRect, saveRect, savedRect } from "@/lib/terminal-window";

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

  describe("resized from an edge or corner", () => {
    const start = { x: 400, y: 100, width: 600, height: 500 };

    it("moves only that edge, keeping the opposite one where it is", () => {
      expect(resizeRect(start, "e", 50, 99, screen)).toEqual({ ...start, width: 650 });
      expect(resizeRect(start, "s", 99, 40, screen)).toEqual({ ...start, height: 540 });
      expect(resizeRect(start, "w", -100, 99, screen)).toEqual({ ...start, x: 300, width: 700 });
      expect(resizeRect(start, "n", 99, 30, screen)).toEqual({ ...start, y: 130, height: 470 });
      expect(resizeRect(start, "nw", -50, -20, screen)).toEqual({ x: 350, y: 80, width: 650, height: 520 });
      expect(resizeRect(start, "se", 10, 10, screen)).toEqual({ ...start, width: 610, height: 510 });
    });

    it("stops at the window's edges", () => {
      expect(resizeRect(start, "e", 5000, 0, screen).width).toBe(screen.width - 8 - start.x);
      expect(resizeRect(start, "s", 0, 5000, screen).height).toBe(screen.height - 8 - start.y);
      expect(resizeRect(start, "w", -5000, 0, screen)).toMatchObject({ x: 8, width: start.x + start.width - 8 });
      expect(resizeRect(start, "n", 0, -5000, screen)).toMatchObject({ y: 8, height: start.y + start.height - 8 });
    });

    it("never gets smaller than a few lines, wherever it's pushed", () => {
      expect(resizeRect(start, "e", -5000, 0, screen).width).toBe(MIN_WINDOW.width);
      expect(resizeRect(start, "s", 0, -5000, screen).height).toBe(MIN_WINDOW.height);
      // From the left or top, the far edge stays put as it stops.
      expect(resizeRect(start, "w", 5000, 0, screen)).toMatchObject({ x: 1000 - 320, width: 320 });
      expect(resizeRect(start, "n", 0, 5000, screen)).toMatchObject({ y: 600 - 240, height: 240 });
    });
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
