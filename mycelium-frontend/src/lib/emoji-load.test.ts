// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The emoji list is a chunk loaded on the first `:`. One that fails to load
// (offline, or a deploy replaced it) mustn't stop messages from sending, and
// mustn't stay failed.

import { describe, expect, it, vi } from "vitest";

const load = vi.hoisted(() => ({ fail: true, attempts: 0 }));

vi.mock("gemoji", () => {
  load.attempts += 1;
  if (load.fail) throw new Error("Loading chunk failed");
  return { gemoji: [{ emoji: "🎉", names: ["tada"], tags: [], description: "party popper", category: "Activities" }] };
});

describe("loading the emoji list", () => {
  it("sends the text as typed when the list can't load, and tries again next time", async () => {
    const { loadEmoji, withEmoji } = await import("@/lib/emoji");
    await expect(loadEmoji()).rejects.toThrow();
    expect(await withEmoji("build failed :x: :tada:", null)).toBe("build failed :x: :tada:");

    load.fail = false;
    vi.resetModules();
    expect(await withEmoji("shipped :tada:", null)).toBe("shipped 🎉");
    expect(load.attempts).toBeGreaterThan(1);
  });
});
