// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Heading styling lives in globals.css, and jsdom does not apply a stylesheet a
// component never imports — so a rendering test cannot see it. This reads the
// rules back out of the source instead and asserts the two properties #888 was
// about: a markdown heading is not label chrome, and the levels form a ramp.

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const CSS_PATH = path.resolve(__dirname, "../app/globals.css");
const LEVELS = [1, 2, 3, 4, 5, 6] as const;

/** Every declaration that reaches `.markdown-body h{level}`, in source order. */
function declarations(level: number): string[] {
  const css = readFileSync(CSS_PATH, "utf-8");
  const selector = new RegExp(`\\.markdown-body h${level}(?![\\d\\w-])`);
  const rules = css.matchAll(/([^{}]+)\{([^{}]*)\}/g);
  return [...rules]
    .filter(([, sel]) => selector.test(sel) && !sel.includes("+"))
    .flatMap(([, , body]) => body.split(";").map(d => d.trim()))
    .filter(Boolean);
}

/** The `font-size` a level resolves to, as a multiple of the body's own size. */
function fontSize(level: number): number {
  const declared = declarations(level).filter(d => d.startsWith("font-size:"));
  const last = declared.at(-1);
  expect(last, `h${level} declares no font-size`).toBeDefined();
  const em = /^font-size:\s*([\d.]+)em$/.exec(last!);
  expect(em, `h${level} sizes in ${last} — the ramp is relative to the body`).not.toBeNull();
  return Number(em![1]);
}

describe("markdown heading styling", () => {
  it("never uppercases a heading", () => {
    for (const level of LEVELS) {
      expect(declarations(level).join("; ")).not.toMatch(/text-transform:\s*uppercase/);
    }
  });

  it("descends in size, so the levels read as a hierarchy", () => {
    const sizes = LEVELS.map(fontSize);
    expect(sizes[0]).toBeGreaterThan(1);
    for (let i = 1; i < sizes.length; i++) {
      expect(sizes[i], `h${i + 1} is larger than h${i}`).toBeLessThanOrEqual(sizes[i - 1]);
    }
  });
});
