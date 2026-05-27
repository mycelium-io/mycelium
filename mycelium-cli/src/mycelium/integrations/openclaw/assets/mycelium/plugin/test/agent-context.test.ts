// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Tests for the @handle-dispatch room-plan briefing: fetch + per-room cache
 * + block rendering.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  _resetAgentContextCacheForTest,
  fetchAgentContext,
  humanizeAge,
  renderPlanBlock,
} from "../src/channel/agent-context.js";

afterEach(() => {
  _resetAgentContextCacheForTest();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const okResponse = (body: unknown) =>
  ({ ok: true, json: async () => body }) as unknown as Response;

describe("fetchAgentContext", () => {
  it("fetches and returns context + generatedAt", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        okResponse({ context: "Open tasks (1):\n- [tasks] x", generated_at: "2026-05-21T18:00:00Z" }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const entry = await fetchAgentContext("http://hub", "room-a", "alpha");
    expect(entry.context).toContain("Open tasks (1)");
    expect(entry.generatedAt).toBe("2026-05-21T18:00:00Z");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("caches per-room — a second call within TTL does not refetch", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(okResponse({ context: "ctx", generated_at: "2026-05-21T18:00:00Z" }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAgentContext("http://hub", "room-a", "alpha");
    await fetchAgentContext("http://hub", "room-a", "alpha");
    await fetchAgentContext("http://hub", "room-a", "beta"); // same room, different handle
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("fetches separately for different rooms", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(okResponse({ context: "ctx", generated_at: "" }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAgentContext("http://hub", "room-a", "alpha");
    await fetchAgentContext("http://hub", "room-b", "alpha");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("returns a null-context entry on fetch failure (never throws)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("network down")),
    );
    const entry = await fetchAgentContext("http://hub", "room-a", "alpha");
    expect(entry.context).toBeNull();
  });

  it("returns a null-context entry on non-ok HTTP status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 500 } as Response),
    );
    const entry = await fetchAgentContext("http://hub", "room-a", "alpha");
    expect(entry.context).toBeNull();
  });

  it("reuses a stale cache entry when a later refetch fails", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce(
          okResponse({ context: "good", generated_at: "2026-05-21T18:00:00Z" }),
        )
        .mockRejectedValue(new Error("later failure"));
      vi.stubGlobal("fetch", fetchMock);

      const first = await fetchAgentContext("http://hub", "room-a", "alpha");
      expect(first.context).toBe("good");

      // Advance past the 60s TTL so the next call refetches — and fails.
      vi.advanceTimersByTime(61_000);
      const second = await fetchAgentContext("http://hub", "room-a", "alpha");
      expect(second.context).toBe("good"); // stale value reused, not null
      expect(fetchMock).toHaveBeenCalledTimes(2); // it really did try again
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("renderPlanBlock", () => {
  it("returns '' when context is null", () => {
    expect(renderPlanBlock(null, "2026-05-21T18:00:00Z")).toBe("");
  });

  it("renders a block with the staleness hint when context is present", () => {
    const block = renderPlanBlock("Open tasks (1):\n- [tasks] x", "2026-05-21T18:00:00Z");
    expect(block).toContain("## Room plan");
    expect(block).toContain("Open tasks (1)");
    expect(block).toContain("mycelium plan tasks");
  });
});

describe("humanizeAge", () => {
  it("returns '' for an empty or unparseable timestamp", () => {
    expect(humanizeAge("")).toBe("");
    expect(humanizeAge("not-a-date")).toBe("");
  });

  it("says 'just now' for a fresh timestamp", () => {
    expect(humanizeAge(new Date().toISOString())).toContain("just now");
  });

  it("reports minutes for an older timestamp", () => {
    const tenMinAgo = new Date(Date.now() - 10 * 60_000).toISOString();
    expect(humanizeAge(tenMinAgo)).toContain("~10 min ago");
  });
});
