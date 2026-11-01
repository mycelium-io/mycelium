// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { claimToSpeak, UNFOCUSED_DELAY_MS, type TabEnv } from "./speaking-tab";

/** Web Locks shared by every tab in a test: `ifAvailable` gets a lock only
 *  when nobody holds it. */
function sharedLocks() {
  const held = new Set<string>();
  return {
    held,
    request: (async (name: string, _opts: LockOptions, cb: (lock: Lock | null) => Promise<unknown>) => {
      if (held.has(name)) return cb(null);
      held.add(name);
      try {
        return await cb({ name, mode: "exclusive" } as Lock);
      } finally {
        held.delete(name);
      }
    }) as unknown as LockManager["request"],
  };
}

function tab(state: { visible: boolean; focused: boolean }, locks: TabEnv["locks"], slept: number[] = []): TabEnv {
  return {
    visible: () => state.visible,
    focused: () => state.focused,
    locks,
    // A claim's hold never ends in a test, so the lock stays taken.
    sleep: (ms) => (ms === UNFOCUSED_DELAY_MS ? (slept.push(ms), Promise.resolve()) : new Promise(() => {})),
  };
}

describe("claimToSpeak", () => {
  it("never speaks from a hidden tab", async () => {
    const locks = sharedLocks();
    expect(await claimToSpeak("m1", tab({ visible: false, focused: false }, locks))).toBe(false);
    expect(locks.held.size).toBe(0);
  });

  it("lets exactly one visible tab read each message", async () => {
    const locks = sharedLocks();
    const focused = tab({ visible: true, focused: true }, locks);
    const beside = tab({ visible: true, focused: false }, locks);
    const [a, b] = await Promise.all([claimToSpeak("m1", focused), claimToSpeak("m1", beside)]);
    expect([a, b]).toEqual([true, false]);
    // A later message is free again.
    expect(await claimToSpeak("m2", beside)).toBe(true);
  });

  it("gives a focused tab a head start over a visible one", async () => {
    const locks = sharedLocks();
    const slept: number[] = [];
    await claimToSpeak("m1", tab({ visible: true, focused: false }, locks, slept));
    expect(slept).toEqual([UNFOCUSED_DELAY_MS]);
  });

  it("doesn't speak from a window hidden during its wait", async () => {
    const state = { visible: true, focused: false };
    const env = tab(state, sharedLocks());
    env.sleep = async () => {
      state.visible = false;
    };
    expect(await claimToSpeak("m1", env)).toBe(false);
  });

  it("without Web Locks, only the focused tab speaks", async () => {
    expect(await claimToSpeak("m1", tab({ visible: true, focused: true }, null))).toBe(true);
    expect(await claimToSpeak("m1", tab({ visible: true, focused: false }, null))).toBe(false);
  });
});
