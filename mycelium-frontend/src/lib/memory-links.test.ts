// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { neighborKeys } from "@/lib/memory-links";
import type { MemoryLink } from "@/lib/api";

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
