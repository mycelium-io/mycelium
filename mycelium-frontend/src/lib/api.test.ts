// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  MEMORIES_MAX,
  MEMORIES_PAGE_LIMIT,
  deleteRoom,
  fetchMemories,
  fetchMemorySummaries,
} from "@/lib/api";

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

describe("fetchMemorySummaries", () => {
  it("reads the list without text, a page at a time like the full one", async () => {
    const fetch = hubWith(MEMORIES_PAGE_LIMIT + 3);
    vi.stubGlobal("fetch", fetch);
    const listed = await fetchMemorySummaries("busy", "work/");
    expect(listed).toHaveLength(MEMORIES_PAGE_LIMIT + 3);
    const urls = fetch.mock.calls.map(([url]) => new URL(String(url), "http://hub"));
    expect(urls.map((u) => u.pathname)).toEqual([
      "/api/rooms/busy/memory/summaries",
      "/api/rooms/busy/memory/summaries",
    ]);
    expect(urls[0].searchParams.get("prefix")).toBe("work/");
  });

  /** A hub from before the light list: `summaries` reads as a memory's key. */
  function olderHub(status = 404) {
    const full = [
      { key: "work/refunds", value: "# Refund the double charge\n\nIn full.", version: 2, created_by: "builder", updated_at: "" },
      { key: "context/limits", value: { max_items: 40 }, content_text: "max_items: 40", version: 1, created_by: "design", updated_at: "" },
    ];
    return vi.fn(async (url: string) => {
      const answer = (ok: boolean, code: number, body: unknown) => ({
        ok,
        status: code,
        json: async () => body,
        text: async () => JSON.stringify(body),
      });
      if (new URL(url, "http://hub").pathname.endsWith("/summaries")) {
        return answer(false, status, { detail: "No memory 'summaries' in room 'busy'" });
      }
      return answer(true, 200, full);
    });
  }

  it("reads the full list and names each memory itself on a hub without the light one", async () => {
    vi.stubGlobal("fetch", olderHub());
    const listed = await fetchMemorySummaries("busy");
    expect(listed.map((m) => [m.key, m.title, m.structured])).toEqual([
      ["work/refunds", "Refund the double charge", false],
      ["context/limits", "max_items: 40", true],
    ]);
    expect(listed[0]).not.toHaveProperty("value");
  });

  it("reads nothing else when the hub fails some other way", async () => {
    const fetch = olderHub(500);
    vi.stubGlobal("fetch", fetch);
    expect(await fetchMemorySummaries("busy")).toEqual([]);
    expect(fetch).toHaveBeenCalledTimes(1);
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
