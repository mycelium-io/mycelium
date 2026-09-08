// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  ACTIVITY_TYPE,
  DEFAULT_TTL_MS,
  applyActivity,
  expireActivity,
  isActivityFrame,
  respondingLabel,
  respondingNames,
  settleActivity,
  splitActivity,
  type Responding,
} from "@/lib/activity";

const T0 = 1_000_000;
const frame = (handle: string, state: "responding" | "done", extra: Record<string, unknown> = {}) => ({
  type: ACTIVITY_TYPE,
  message_type: ACTIVITY_TYPE,
  handle,
  state,
  ...extra,
});

describe("recognising an activity frame", () => {
  it("accepts the backend's shape by either type field", () => {
    expect(isActivityFrame(frame("aligner", "responding"))).toBe(true);
    expect(isActivityFrame({ message_type: ACTIVITY_TYPE, handle: "x", state: "done" })).toBe(true);
  });

  it("refuses a chat message, and an activity frame with no handle or an unknown state", () => {
    expect(isActivityFrame({ message_type: "broadcast", sender_handle: "x", content: "hi" })).toBe(false);
    expect(isActivityFrame({ type: ACTIVITY_TYPE, state: "responding" })).toBe(false);
    expect(isActivityFrame({ type: ACTIVITY_TYPE, handle: "x", state: "thinking" })).toBe(false);
  });
});

describe("folding frames", () => {
  it("a responding adds one entry per handle, with the frame's TTL", () => {
    const next = applyActivity([], frame("aligner", "responding", { ttl_s: 30, episode: "urn:e1" }), T0);
    expect(next).toEqual<Responding[]>([{ handle: "aligner", episode: "urn:e1", since: T0, until: T0 + 30_000 }]);
  });

  it("a second responding for the same handle refreshes rather than duplicates", () => {
    let s = applyActivity([], frame("aligner", "responding"), T0);
    s = applyActivity(s, frame("@Aligner", "responding"), T0 + 5_000);
    expect(s).toHaveLength(1);
    expect(s[0].since).toBe(T0 + 5_000);
    expect(s[0].until).toBe(T0 + 5_000 + DEFAULT_TTL_MS);
  });

  it("done removes the handle and leaves the others", () => {
    let s = applyActivity([], frame("aligner", "responding"), T0);
    s = applyActivity(s, frame("growth", "responding"), T0);
    s = applyActivity(s, frame("aligner", "done"), T0 + 1);
    expect(s.map((r) => r.handle)).toEqual(["growth"]);
  });

  it("done for a handle that was never responding is a no-op", () => {
    expect(applyActivity([], frame("ghost", "done"), T0)).toEqual([]);
  });
});

describe("settling and expiring", () => {
  it("a message from the handle ends its turn", () => {
    const s = applyActivity([], frame("growth", "responding"), T0);
    expect(settleActivity(s, "growth")).toEqual([]);
    expect(settleActivity(s, "@GROWTH")).toEqual([]);
  });

  it("a message from someone else leaves it standing, and returns the same array", () => {
    const s = applyActivity([], frame("growth", "responding"), T0);
    expect(settleActivity(s, "finance")).toBe(s);
    expect(settleActivity(s, null)).toBe(s);
  });

  it("an entry past its TTL is dropped; an untouched list is the same array", () => {
    const s = applyActivity([], frame("growth", "responding", { ttl_s: 10 }), T0);
    expect(expireActivity(s, T0 + 9_999)).toBe(s);
    expect(expireActivity(s, T0 + 10_000)).toEqual([]);
  });
});

describe("the line", () => {
  const at = (...handles: string[]): Responding[] =>
    handles.map((h) => ({ handle: h, episode: null, since: T0, until: T0 + 1 }));

  it("reads naturally for one, two and many", () => {
    expect(respondingLabel([])).toBe("");
    expect(respondingLabel(at("aligner"))).toBe("@aligner is responding…");
    expect(respondingLabel(at("growth", "finance"))).toBe("@growth and @finance are responding…");
    expect(respondingLabel(at("a", "b", "c"))).toBe("@a, @b and 1 other are responding…");
    expect(respondingLabel(at("a", "b", "c", "d"))).toBe("@a, @b and 2 others are responding…");
    expect(respondingNames(at("a", "b"))).toBe("@a and @b");
  });

  it("stops short of the thread's name when the turn is going elsewhere", () => {
    expect(respondingLabel(at("aligner"), "elsewhere")).toBe("@aligner is responding in");
    expect(respondingLabel(at("a", "b"), "elsewhere")).toBe("@a and @b are responding in");
  });
});

describe("splitting by where the turn lands", () => {
  const entry = (handle: string, episode: string | null): Responding => ({ handle, episode, since: T0, until: T0 + 1 });
  const live = "urn:ioc:mycelium:episode:atlas:live";

  it("keeps room-level turns here and groups thread turns by their thread", () => {
    const { here, elsewhere } = splitActivity(
      [entry("growth", null), entry("aligner", "urn:e1"), entry("finance", live), entry("risk", "urn:e1"), entry("ops", "urn:e2")],
      (episode) => !episode || episode === live,
    );
    expect(here.map((r) => r.handle)).toEqual(["growth", "finance"]);
    expect([...elsewhere.keys()]).toEqual(["urn:e1", "urn:e2"]);
    expect(elsewhere.get("urn:e1")?.map((r) => r.handle)).toEqual(["aligner", "risk"]);
  });

  it("inside a thread, only that thread's turns are here", () => {
    const { here, elsewhere } = splitActivity(
      [entry("growth", null), entry("aligner", "urn:e1")],
      (episode) => episode === "urn:e1",
    );
    expect(here.map((r) => r.handle)).toEqual(["aligner"]);
    expect(elsewhere.get("")?.map((r) => r.handle)).toEqual(["growth"]);
  });
});
