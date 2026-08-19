// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { integrityNotesForMemory, neighborKeys } from "@/lib/memory-links";
import type { MemoryLink, MemoryLinksIntegrity } from "@/lib/api";

const link = (over: Partial<MemoryLink>): MemoryLink => ({
  target: "b",
  kind: "wikilink",
  raw: "[[b]]",
  resolved: true,
  ...over,
});

describe("neighborKeys", () => {
  it("collects outbound targets and backlink sources, excluding self", () => {
    const outbound = [link({ target: "decisions/a" }), link({ target: "context/b" })];
    const backlinks = [link({ source: "context/c", target: "here" })];
    expect(neighborKeys("here", outbound, backlinks)).toEqual(["context/b", "context/c", "decisions/a"]);
  });

  it("dedupes when the same key appears twice", () => {
    const outbound = [link({ target: "a" }), link({ target: "a" })];
    expect(neighborKeys("here", outbound, [])).toEqual(["a"]);
  });
});

describe("integrityNotesForMemory", () => {
  const integrity: MemoryLinksIntegrity = {
    broken: [{ source: "here", target: "gone", kind: "wikilink", raw: "[[gone]]", resolved: false }],
    orphans: ["lonely"],
    total_memories: 2,
    total_links: 1,
  };

  it("returns null when the memory has no integrity issues", () => {
    expect(integrityNotesForMemory("ok", integrity)).toBeNull();
  });

  it("counts broken outbound from this key", () => {
    expect(integrityNotesForMemory("here", integrity)).toEqual({
      brokenOutbound: 1,
      isOrphan: false,
    });
  });

  it("flags orphans", () => {
    expect(integrityNotesForMemory("lonely", integrity)).toEqual({
      brokenOutbound: 0,
      isOrphan: true,
    });
  });
});
