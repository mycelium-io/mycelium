// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { filterWikilinkCandidates, matchWikilinkAt } from "@/lib/wikilink-completions";

describe("matchWikilinkAt", () => {
  it("matches a bare sigil with no query yet", () => {
    expect(matchWikilinkAt("see [[")).toEqual({ offset: 4, query: "", sigil: "[[" });
  });

  it("captures the partial key typed after the sigil", () => {
    expect(matchWikilinkAt("see [[context/anch")).toEqual({
      offset: 4,
      query: "context/anch",
      sigil: "[[",
    });
  });

  it("distinguishes a transclusion sigil", () => {
    expect(matchWikilinkAt("![[glossary")).toEqual({
      offset: 0,
      query: "glossary",
      sigil: "![[",
    });
  });

  it("returns null when the cursor is not inside a wikilink", () => {
    expect(matchWikilinkAt("just some prose")).toBeNull();
    expect(matchWikilinkAt("")).toBeNull();
  });

  it("returns null once the link is closed", () => {
    expect(matchWikilinkAt("see [[context/anchor]]")).toBeNull();
  });

  it("does not reach back to a closed link earlier on the line", () => {
    expect(matchWikilinkAt("see [[a]] and then some prose")).toBeNull();
  });

  it("stops at a space, so prose after a stray bracket does not match", () => {
    expect(matchWikilinkAt("[[ not a key")).toBeNull();
  });

  it("reports the offset of the sigil, not of the query", () => {
    // The offset drives the replacement range: starting it after the sigil
    // would append the inserted `[[key]]` to the `[[` already typed.
    const token = matchWikilinkAt("prefix ![[ctx");
    expect(token?.offset).toBe(7);
    expect("prefix ![[ctx".slice(token!.offset)).toBe("![[ctx");
  });
});

describe("filterWikilinkCandidates", () => {
  const keys = ["context/anchor", "context/overview", "decisions/db-choice"];

  it("returns every key for an empty query", () => {
    expect(filterWikilinkCandidates(keys, "")).toEqual(keys);
  });

  it("matches on any substring, not just a prefix", () => {
    expect(filterWikilinkCandidates(keys, "anchor")).toEqual(["context/anchor"]);
  });

  it("is case insensitive", () => {
    expect(filterWikilinkCandidates(keys, "DB-CHOICE")).toEqual(["decisions/db-choice"]);
  });

  it("returns nothing when no key matches", () => {
    expect(filterWikilinkCandidates(keys, "nope")).toEqual([]);
  });

  it("handles an empty pool", () => {
    expect(filterWikilinkCandidates([], "anything")).toEqual([]);
  });
});
