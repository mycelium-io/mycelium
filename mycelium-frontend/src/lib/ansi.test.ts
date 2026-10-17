// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { color256, parseAnsi } from "@/lib/ansi";

describe("parseAnsi", () => {
  it("splits a screen into lines and keeps plain text whole", () => {
    expect(parseAnsi("one\r\ntwo\r\n")).toEqual([
      [{ text: "one", style: {} }],
      [{ text: "two", style: {} }],
    ]);
  });

  it("styles each run by the escapes before it, and resets on 0", () => {
    const [line] = parseAnsi("\x1b[1m\x1b[38;5;2mjulia\x1b[0m@mbp");
    expect(line).toEqual([
      { text: "julia", style: { bold: true, fg: color256(2) } },
      { text: "@mbp", style: {} },
    ]);
  });

  it("reads 16-color, 256-color and true-color foregrounds and backgrounds", () => {
    const [line] = parseAnsi("\x1b[31ma\x1b[48;2;10;20;30mb\x1b[39;49mc");
    expect(line.map((r) => r.style)).toEqual([
      { fg: color256(1) },
      { fg: color256(1), bg: "rgb(10, 20, 30)" },
      {},
    ]);
  });

  it("drops control sequences it doesn't draw, and keeps blank lines", () => {
    expect(parseAnsi("\x1b[2J\x1b[Hhi\x1b]0;title\x07\n\nthere")).toEqual([
      [{ text: "hi", style: {} }],
      [],
      [{ text: "there", style: {} }],
    ]);
  });
});

describe("color256", () => {
  it("covers the cube and the greys", () => {
    expect(color256(16)).toBe("rgb(0, 0, 0)");
    expect(color256(231)).toBe("rgb(255, 255, 255)");
    expect(color256(232)).toBe("rgb(8, 8, 8)");
  });
});
