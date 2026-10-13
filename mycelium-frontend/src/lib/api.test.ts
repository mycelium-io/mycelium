// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { beforeEach, describe, expect, it, vi } from "vitest";
import { MEMORIES_MAX, MEMORIES_PAGE_LIMIT, deleteRoom, fetchMemories } from "@/lib/api";

/** A hub holding `total` memories, serving them a page at a time like the real one. */
function hubWith(total: number, { writeAfterFirstPage = false } = {}) {
  const keys = Array.from({ length: total }, (_, i) => `notes/${i}`);
  return vi.fn(async (url: string) => {
    const params = new URL(url, "http://hub").searchParams;
    const offset = Number(params.get("offset") ?? 0);
    const limit = Number(params.get("limit") ?? 100);
    const page = keys.slice(offset, offset + limit).map((key) => ({ key, value: key }));
    // A memory written between two calls lands first, shifting every later page by one.
    if (writeAfterFirstPage && offset === 0) keys.unshift("notes/new");
    return { ok: true, status: 200, json: async () => page, text: async () => JSON.stringify(page) };
  });
}

describe("fetchMemories", () => {
  it("keeps a memory once when a write shifts the pages mid-read", async () => {
    vi.stubGlobal("fetch", hubWith(MEMORIES_PAGE_LIMIT + 10, { writeAfterFirstPage: true }));
    const memories = await fetchMemories("busy");
    const keys = memories.map((m) => m.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys).toHaveLength(MEMORIES_PAGE_LIMIT + 10);
  });

  it("reads every page of a room with more memories than one call serves", async () => {
    const fetch = hubWith(MEMORIES_PAGE_LIMIT * 2 + 7);
    vi.stubGlobal("fetch", fetch);
    const memories = await fetchMemories("busy");
    expect(memories).toHaveLength(MEMORIES_PAGE_LIMIT * 2 + 7);
    expect(new Set(memories.map((m) => m.key)).size).toBe(memories.length);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("makes one call for a room that fits in a page", async () => {
    const fetch = hubWith(221);
    vi.stubGlobal("fetch", fetch);
    expect(await fetchMemories("general")).toHaveLength(221);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("stops at the cap, newest first", async () => {
    vi.stubGlobal("fetch", hubWith(MEMORIES_MAX + 500));
    const memories = await fetchMemories("huge");
    expect(memories).toHaveLength(MEMORIES_MAX);
    expect(memories[0].key).toBe("notes/0");
  });
});

describe("deleteRoom", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
      }),
    );
  });

  it("encodes room names and accepts an empty 204 response", async () => {
    await deleteRoom("design review/é");

    expect(fetch).toHaveBeenCalledWith("/api/rooms/design%20review%2F%C3%A9", {
      method: "DELETE",
    });
  });
});
