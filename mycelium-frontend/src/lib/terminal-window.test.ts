// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { beforeEach, describe, expect, it } from "vitest";
import { MIN_WINDOW, clampRect, defaultRect, saveRect, savedRect } from "@/lib/terminal-window";

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

  it("is put back on a screen that shrank, header and all", () => {
    const r = clampRect({ x: 2400, y: 1300, width: 640, height: 680 }, screen);
    expect(r.x).toBeLessThan(screen.width);
    expect(r.y).toBeLessThan(screen.height);
    expect(clampRect({ x: 100, y: -50, width: 640, height: 680 }, screen).y).toBe(0);
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
