// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { expandedPathsForKey } from "@/lib/memory-panel-nav";

describe("expandedPathsForKey", () => {
  it("returns namespace prefixes to uncollapse", () => {
    expect(expandedPathsForKey("context/overview")).toEqual(["context"]);
    expect(expandedPathsForKey("a/b/c")).toEqual(["a", "a/b"]);
  });
});
