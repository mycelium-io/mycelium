import { describe, expect, it } from "vitest";
import { diffLines } from "./agent-session";

describe("diffLines", () => {
  it("marks a replaced line as one removed and the new ones added", () => {
    const d = diffLines("a\nreturn x;\nb", "a\nconst k = key();\nreturn x(k);\nb");
    expect(d.lines).toEqual(["  a", "- return x;", "+ const k = key();", "+ return x(k);", "  b"]);
    expect([d.added, d.removed]).toEqual([2, 1]);
  });

  it("counts a new file as all added", () => {
    expect(diffLines(null, "one\ntwo")).toEqual({ lines: ["+ one", "+ two"], added: 2, removed: 0 });
  });

  it("finds no change in the same text", () => {
    expect(diffLines("same", "same")).toEqual({ lines: ["  same"], added: 0, removed: 0 });
  });
});
