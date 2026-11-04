import { describe, expect, it } from "vitest";
import { diffLines, mergeLive, prependPage, type SessionEntry } from "./agent-session";

const entry = (id: string): SessionEntry => ({ sessionUpdate: "compaction", _meta: { id, at: "" } });
const ids = (list: SessionEntry[]) => list.map((e) => e._meta.id).join("");

describe("mergeLive", () => {
  it("keeps what slid out of the live read", () => {
    const held = ["a", "b", "c", "d"].map(entry);
    expect(ids(mergeLive(held, ["c", "d", "e"].map(entry)))).toBe("abcde");
  });

  it("lets go of what it held when the live read has moved past all of it", () => {
    expect(ids(mergeLive(["a", "b"].map(entry), ["x", "y"].map(entry)))).toBe("xy");
  });
});

describe("prependPage", () => {
  it("puts a page before what's held, once", () => {
    expect(ids(prependPage(["c", "d"].map(entry), ["a", "b", "c"].map(entry)))).toBe("abcd");
  });
});

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
