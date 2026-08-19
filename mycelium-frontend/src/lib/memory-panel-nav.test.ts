// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it, vi } from "vitest";
import { expandedPathsForKey, resolveMemoryPeekNavigation } from "@/lib/memory-panel-nav";
import type { Memory } from "@/lib/api";

const mem = (key: string): Memory => ({
  key,
  value: { text: "body" },
  content_text: "body",
  version: 1,
  created_by: "alice",
  updated_at: "2026-01-01T00:00:00Z",
});

describe("resolveMemoryPeekNavigation", () => {
  it("opens the drawer from the loaded list without fetching", async () => {
    const fetchByKey = vi.fn();
    const result = await resolveMemoryPeekNavigation(
      "demo",
      "context/overview",
      [mem("context/overview")],
      fetchByKey,
    );
    expect(result).toEqual({ action: "drawer", memory: mem("context/overview") });
    expect(fetchByKey).not.toHaveBeenCalled();
  });

  it("fetches by key when missing from the loaded list (limit-50 / empty tree)", async () => {
    const offTree = mem("context/off-tree");
    const fetchByKey = vi.fn().mockResolvedValue(offTree);
    const result = await resolveMemoryPeekNavigation("demo", "context/off-tree", [], fetchByKey);
    expect(fetchByKey).toHaveBeenCalledWith("demo", "context/off-tree");
    expect(result).toEqual({ action: "drawer", memory: offTree });
  });

  it("routes to full page only when the memory does not exist", async () => {
    const fetchByKey = vi.fn().mockResolvedValue(null);
    const result = await resolveMemoryPeekNavigation("demo", "missing/key", [], fetchByKey);
    expect(result).toEqual({
      action: "full-page",
      href: "/room/demo/memory/missing/key",
    });
  });
});

describe("expandedPathsForKey", () => {
  it("returns namespace prefixes to uncollapse", () => {
    expect(expandedPathsForKey("context/overview")).toEqual(["context"]);
    expect(expandedPathsForKey("a/b/c")).toEqual(["a", "a/b"]);
  });
});
