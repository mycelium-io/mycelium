// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";

import { centerOn, clampPan, FIT, inView, maxScale, panBy, readout, toggleAt, zoomAt } from "@/lib/zoom";

const BOX = { width: 500, height: 400 };
// Twice the box's width, so 100% is a scale of 2.
const NATURAL = 1000;

describe("zoomAt", () => {
  it("keeps the point under the pointer where it is", () => {
    const v = zoomAt(FIT, 2, { x: 100, y: 50 }, BOX, 8);
    expect(v).toEqual({ scale: 2, x: -100, y: -50 });
    // The image point that was at (100, 50) is drawn at (100, 50) still.
    expect(v.x + 100 * v.scale).toBe(100);
  });

  it("clamps between fit and the most it zooms", () => {
    expect(zoomAt(FIT, 0.5, { x: 0, y: 0 }, BOX, 8)).toEqual(FIT);
    expect(zoomAt(FIT, 20, { x: 0, y: 0 }, BOX, 8).scale).toBe(8);
  });

  it("zooms in further when 100% is past 8x", () => {
    expect(maxScale(BOX, NATURAL)).toBe(8);
    expect(maxScale(BOX, 5000)).toBe(10);
  });
});

describe("panning", () => {
  it("never shows past an edge of the image", () => {
    const v = { scale: 2, x: -100, y: -100 };
    expect(panBy(v, 500, 500, BOX)).toEqual({ scale: 2, x: 0, y: 0 });
    expect(panBy(v, -5000, -5000, BOX)).toEqual({ scale: 2, x: -500, y: -400 });
    expect(clampPan({ scale: 2, x: -250, y: -10 }, BOX)).toEqual({ scale: 2, x: -250, y: -10 });
  });

  it("does nothing at fit", () => {
    expect(panBy(FIT, 40, 40, BOX)).toBe(FIT);
  });
});

describe("toggleAt", () => {
  it("goes to 100% at the point, then back to fit", () => {
    const actual = toggleAt(FIT, { x: 0, y: 0 }, BOX, NATURAL);
    expect(actual.scale).toBe(2);
    expect(toggleAt(actual, { x: 0, y: 0 }, BOX, NATURAL)).toEqual(FIT);
  });

  it("goes to 2x when the image already fits at its own size", () => {
    expect(toggleAt(FIT, { x: 0, y: 0 }, BOX, 400).scale).toBe(2);
  });
});

describe("the part in view", () => {
  it("is the box shrunk by the scale, at the offset", () => {
    expect(inView({ scale: 2, x: -100, y: -50 }, BOX)).toEqual({ x: 50, y: 25, width: 250, height: 200 });
  });

  it("can be centered on a point, as far as the edges allow", () => {
    const v = { scale: 2, x: 0, y: 0 };
    expect(centerOn(v, { x: 250, y: 200 }, BOX)).toEqual({ scale: 2, x: -250, y: -200 });
    expect(centerOn(v, { x: 0, y: 0 }, BOX)).toEqual({ scale: 2, x: 0, y: 0 });
    expect(centerOn(FIT, { x: 250, y: 200 }, BOX)).toBe(FIT);
  });
});

describe("readout", () => {
  it("says fit, or the share of the image's own size", () => {
    expect(readout(FIT, BOX, NATURAL)).toBe("Fit");
    expect(readout({ scale: 2, x: 0, y: 0 }, BOX, NATURAL)).toBe("100%");
    expect(readout({ scale: 1.25, x: 0, y: 0 }, BOX, NATURAL)).toBe("63%");
  });
});
