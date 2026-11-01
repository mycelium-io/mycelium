// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { AGENT_FAMILIES, detailFor, genome, pxOfSizeClass } from "./sporelings";

describe("sporelings", () => {
  it("draws the same creature for the same handle, every time", () => {
    expect(genome("mycelium-coder")).toEqual(genome("mycelium-coder"));
    // Case and stray spaces don't make a different creature.
    expect(genome("Mycelium-Coder ")).toEqual(genome("mycelium-coder"));
  });

  it("makes every engine a lantern and no agent one", () => {
    expect(genome("conductor", true).family).toBe("lantern");
    for (let i = 0; i < 200; i++) expect(genome(`agent-${i}`).family).not.toBe("lantern");
  });

  it("spreads agents across every family", () => {
    const seen = new Map<string, number>();
    for (let i = 0; i < 500; i++) {
      const f = genome(`agent-${i}`).family;
      seen.set(f, (seen.get(f) ?? 0) + 1);
    }
    expect([...seen.keys()].sort()).toEqual([...AGENT_FAMILIES].sort());
    // No family takes more than a third of a room.
    for (const n of seen.values()) expect(n).toBeLessThan(500 / 3);
  });

  it("keeps the lean small enough to stay in the circle", () => {
    for (let i = 0; i < 200; i++) expect(Math.abs(genome(`agent-${i}`).tilt)).toBeLessThanOrEqual(5);
  });

  it("draws a glyph below 28px and the simple creature from 28px", () => {
    expect(detailFor(16)).toBe("glyph");
    expect(detailFor(20)).toBe("glyph");
    expect(detailFor(24)).toBe("glyph");
    expect(detailFor(28)).toBe("simple");
    expect(detailFor(40)).toBe("simple");
  });

  it("reads the size from a Tailwind size class", () => {
    expect(pxOfSizeClass("size-5 text-[9px]")).toBe(20);
    expect(pxOfSizeClass("shrink-0 size-7")).toBe(28);
    expect(pxOfSizeClass("text-label size-10")).toBe(40);
    expect(pxOfSizeClass(undefined)).toBe(32);
    expect(pxOfSizeClass("text-[10px]")).toBe(32);
  });
});
