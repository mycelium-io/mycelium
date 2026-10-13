// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";

import {
  centerOn,
  clampPan,
  fitView,
  inView,
  maxScale,
  panBy,
  readout,
  stageOf,
  toggleAt,
  zoomAt,
  type Stage,
} from "@/lib/zoom";

// One frame, the shape of a window, whatever the image.
const FRAME = { width: 1000, height: 700 };
// A tall phone screenshot (1:3), a wide one (3:1), and a small icon.
const TALL = stageOf(FRAME, { width: 600, height: 1800 });
const WIDE = stageOf(FRAME, { width: 3000, height: 1000 });
const SMALL = stageOf(FRAME, { width: 200, height: 100 });

const near = (n: number) => Math.round(n * 100) / 100;
const round = (v: { scale: number; x: number; y: number }) => ({ scale: near(v.scale), x: near(v.x), y: near(v.y) });
const drawn = (st: Stage, scale: number) => ({ width: st.fitted.width * scale, height: st.fitted.height * scale });

describe("fit", () => {
  it("contains the image in the frame, and never enlarges it past its own size", () => {
    expect(near(TALL.fitted.width)).toBe(233.33);
    expect(TALL.fitted.height).toBe(700);
    expect(WIDE.fitted.width).toBe(1000);
    expect(near(WIDE.fitted.height)).toBe(333.33);
    expect(SMALL.fitted).toEqual({ width: 200, height: 100 });
  });

  it("starts whole and centered", () => {
    expect(round(fitView(TALL))).toEqual({ scale: 1, x: 383.33, y: 0 });
    expect(round(fitView(WIDE))).toEqual({ scale: 1, x: 0, y: 183.33 });
    expect(fitView(SMALL)).toEqual({ scale: 1, x: 400, y: 300 });
  });
});

describe("zooming a tall image", () => {
  it("grows past the frame on both axes, so it fills the frame's width", () => {
    const v = zoomAt(fitView(TALL), 5, { x: 500, y: 350 }, TALL);
    expect(drawn(TALL, v.scale).width).toBeGreaterThan(FRAME.width);
    // No empty space shows on either side: the image covers the whole frame.
    expect(v.x).toBeLessThanOrEqual(0);
    expect(v.x + drawn(TALL, v.scale).width).toBeGreaterThanOrEqual(FRAME.width);
    expect(v.y).toBeLessThanOrEqual(0);
    expect(v.y + drawn(TALL, v.scale).height).toBeGreaterThanOrEqual(FRAME.height);
  });

  it("keeps the point under the pointer still, as far as the edges allow", () => {
    const start = fitView(TALL);
    const point = { x: 500, y: 350 };
    const v = zoomAt(start, 2, point, TALL);
    // The image point under (500, 350) before is still under it.
    expect(near((point.y - v.y) / v.scale)).toBe(near((point.y - start.y) / start.scale));
  });

  it("keeps a side still narrower than the frame centered on it", () => {
    const v = zoomAt(fitView(TALL), 2, { x: 0, y: 0 }, TALL);
    const width = drawn(TALL, 2).width;
    expect(width).toBeLessThan(FRAME.width);
    expect(near(v.x)).toBe(near((FRAME.width - width) / 2));
  });

  it("goes back to fit below fit, and stops at the most it zooms", () => {
    expect(zoomAt(fitView(TALL), 0.5, { x: 0, y: 0 }, TALL)).toEqual(fitView(TALL));
    expect(zoomAt(fitView(TALL), 50, { x: 0, y: 0 }, TALL).scale).toBe(maxScale(TALL));
  });
});

describe("panning", () => {
  it("stops at the image's edges and never shows empty space", () => {
    const v = zoomAt(fitView(TALL), 5, { x: 500, y: 0 }, TALL);
    expect(panBy(v, 0, 10_000, TALL).y).toBe(0);
    const bottom = panBy(v, 0, -100_000, TALL);
    expect(near(bottom.y + drawn(TALL, 5).height)).toBe(FRAME.height);
    expect(panBy(v, 10_000, 0, TALL).x).toBe(0);
  });

  it("leaves a wide image's short side centered while it pans along the long one", () => {
    const v = zoomAt(fitView(WIDE), 1.5, { x: 500, y: 350 }, WIDE);
    const moved = panBy(v, -200, -200, WIDE);
    expect(near(moved.y)).toBe(near((FRAME.height - drawn(WIDE, 1.5).height) / 2));
    expect(moved.x).toBeLessThan(v.x);
  });

  it("does nothing at fit", () => {
    expect(panBy(fitView(TALL), 40, 40, TALL)).toEqual(fitView(TALL));
  });

  it("clamps any view back into the frame", () => {
    expect(clampPan({ scale: 1, x: -500, y: 900 }, SMALL)).toEqual(fitView(SMALL));
  });
});

describe("a click", () => {
  it("goes to 100% at the point, then back to fit", () => {
    const actual = toggleAt(fitView(TALL), { x: 500, y: 350 }, TALL);
    expect(near(actual.scale)).toBe(near(600 / TALL.fitted.width));
    expect(readout(actual, TALL)).toBe("100%");
    expect(toggleAt(actual, { x: 0, y: 0 }, TALL)).toEqual(fitView(TALL));
  });

  it("goes to 2x for an image already shown at its own size", () => {
    const v = toggleAt(fitView(SMALL), { x: 500, y: 350 }, SMALL);
    expect(v.scale).toBe(2);
    expect(readout(v, SMALL)).toBe("200%");
  });
});

describe("the part in view", () => {
  it("is the frame's share of the image, in the fitted image's pixels", () => {
    expect(inView({ scale: 5, x: -100, y: -500 }, TALL)).toEqual({ x: 20, y: 100, width: 200, height: 140 });
  });

  it("is the whole width while that side still fits", () => {
    const v = zoomAt(fitView(TALL), 2, { x: 500, y: 350 }, TALL);
    expect(near(inView(v, TALL).width)).toBe(near(TALL.fitted.width));
  });

  it("can be centered on a point, as far as the edges allow", () => {
    const v = zoomAt(fitView(TALL), 5, { x: 500, y: 350 }, TALL);
    const middle = centerOn(v, { x: TALL.fitted.width / 2, y: TALL.fitted.height / 2 }, TALL);
    expect(near(middle.y + (TALL.fitted.height / 2) * 5)).toBe(FRAME.height / 2);
    expect(centerOn(v, { x: 0, y: 0 }, TALL)).toMatchObject({ x: 0, y: 0 });
    expect(centerOn(fitView(TALL), { x: 0, y: 0 }, TALL)).toEqual(fitView(TALL));
  });
});

describe("readout", () => {
  it("says fit, or the share of the image's own size", () => {
    expect(readout(fitView(TALL), TALL)).toBe("Fit");
    expect(readout({ scale: 600 / TALL.fitted.width / 2, x: 0, y: 0 }, TALL)).toBe("50%");
  });
});
