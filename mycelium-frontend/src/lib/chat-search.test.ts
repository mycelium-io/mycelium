// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { countMatches, hasMatch, splitOnMatches, stepIndex } from "@/lib/chat-search";

/** The invariant the whole feature rests on: a split is the text, rearranged. */
const rejoin = (text: string, query: string) =>
  splitOnMatches(text, query)
    .map(s => s.text)
    .join("");

describe("splitOnMatches", () => {
  it("splits around every occurrence, keeping the original casing", () => {
    expect(splitOnMatches("Deploy the deployment", "deploy")).toEqual([
      { text: "Deploy", match: true },
      { text: " the ", match: false },
      { text: "deploy", match: true },
      { text: "ment", match: false },
    ]);
  });

  it("never loses or invents a character", () => {
    for (const query of ["a", "the", "z", "  ", "deploy"]) {
      expect(rejoin("The deploy ran; a deploy again", query)).toBe("The deploy ran; a deploy again");
    }
  });

  it("matches the query literally, so regex metacharacters are just text", () => {
    expect(countMatches("cost is $5 (net) [approx]", "(net)")).toBe(1);
    expect(countMatches("a.b axb", ".")).toBe(1);
    expect(countMatches("aaa", "a+")).toBe(0);
  });

  it("does not overlap its own matches", () => {
    expect(countMatches("aaaa", "aa")).toBe(2);
  });

  it("treats an empty or blank query as no search at all", () => {
    expect(splitOnMatches("anything", "")).toEqual([{ text: "anything", match: false }]);
    expect(splitOnMatches("anything", "   ")).toEqual([{ text: "anything", match: false }]);
    expect(hasMatch("anything", "")).toBe(false);
  });

  it("keeps a query that is blank only at its edges", () => {
    // " the " is a real thing to search for — the guard is against a query with
    // nothing in it, not against one with spaces in it.
    expect(countMatches("in the room", " the ")).toBe(1);
  });

  it("handles empty text", () => {
    expect(splitOnMatches("", "x")).toEqual([]);
    expect(hasMatch("", "x")).toBe(false);
  });
});

describe("hasMatch", () => {
  it("agrees with countMatches on whether there is anything to find", () => {
    for (const [text, query] of [
      ["hello world", "WORLD"],
      ["hello world", "nope"],
      ["", "x"],
      ["x", ""],
    ] as const) {
      expect(hasMatch(text, query)).toBe(countMatches(text, query) > 0);
    }
  });
});

describe("stepIndex", () => {
  it("wraps past the last match back to the first", () => {
    expect(stepIndex(2, 3, 1)).toBe(0);
    expect(stepIndex(0, 3, 1)).toBe(1);
  });

  it("wraps before the first match back to the last", () => {
    expect(stepIndex(0, 3, -1)).toBe(2);
  });

  it("stays at zero when there is nothing to step through", () => {
    expect(stepIndex(0, 0, 1)).toBe(0);
    expect(stepIndex(0, 0, -1)).toBe(0);
  });
});
