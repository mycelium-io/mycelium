// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  ALL_KINDS,
  dayLabel,
  dayOf,
  describe as describeEvent,
  foldEvents,
  lanesOf,
  matches,
  streamEventOf,
  type StreamEvent,
} from "@/lib/room-stream";

const ROOM = "mycelium-general";
const T1 = `urn:ioc:mycelium:episode:${ROOM}:t1`;
const T2 = `urn:ioc:mycelium:episode:${ROOM}:t2`;
const LIVE = `urn:ioc:mycelium:episode:${ROOM}:live`;
let n = 0;

function frame(content: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  n += 1;
  return {
    id: `f${n}`,
    sender_handle: "system",
    message_type: "l9_exchange",
    created_at: `2026-10-11T20:39:${String(n % 60).padStart(2, "0")}Z`,
    content: JSON.stringify(content),
    ...extra,
  };
}

const message = (who: string, text: string, episode = LIVE) =>
  frame({ content: text, l9: { header: { message: { episode } }, payload: { type: "message" } } }, { sender_handle: who });
const notice = (data: Record<string, string>) => frame({ l9: { payload: { type: "notice", data } } });

describe("streamEventOf", () => {
  it("reads a message in a thread and one in the channel", () => {
    expect(streamEventOf(message("julia", "@mycelium-coder add these", T1), ROOM)).toMatchObject({
      kind: "message",
      who: "julia",
      episode: T1,
      mentions: ["mycelium-coder"],
    });
    expect(streamEventOf(message("julia", "morning"), ROOM)?.episode).toBeNull();
  });

  it("reads board and pull request changes as their own kinds", () => {
    const filed = streamEventOf(
      notice({ subkind: "filed", key: "work/a", title: "Build the settings pages", episode: T1, by: "mycelium-chat-buddy", for: "mycelium-coder" }),
      ROOM,
    )!;
    expect(filed).toMatchObject({ kind: "board", who: "mycelium-chat-buddy", episode: T1 });
    expect(describeEvent(filed)).toBe("filed Build the settings pages for mycelium-coder");

    const ci = streamEventOf(notice({ subkind: "upstream", key: "work/a", episode: T1, change: "ci_passed", ref: "o/r#1260" }), ROOM)!;
    expect(ci).toMatchObject({ kind: "github", who: "github" });
    expect(describeEvent(ci)).toBe("CI passed on PR #1260");

    // Led by the pull request, since a person approved it, not GitHub.
    const approved = streamEventOf(notice({ subkind: "upstream", key: "work/a", change: "approved", ref: "o/r#12" }), ROOM)!;
    expect(describeEvent(approved)).toBe("PR #12 approved");
    const asked = streamEventOf(
      notice({ subkind: "upstream", key: "work/a", change: "review_requested", ref: "o/r#12", who: "mycelium-reviewer" }),
      ROOM,
    )!;
    expect(describeEvent(asked)).toBe("review asked on PR #12 of mycelium-reviewer");
  });

  it("says who a reassigned task moved between, and why a hold ended", () => {
    const moved = streamEventOf(
      notice({ subkind: "claimed", key: "work/a", title: "Ship it", by: "lead", for: "coder", from: "tester" }),
      ROOM,
    )!;
    expect(describeEvent(moved)).toBe("claimed Ship it from @tester to @coder");
    const ended = streamEventOf(
      notice({ subkind: "released", key: "work/a", title: "Ship it", by: "runtime", why: "@coder's herdr pane closed" }),
      ROOM,
    )!;
    expect(describeEvent(ended)).toBe("let go of Ship it (@coder's herdr pane closed)");
  });

  it("skips pings, floor changes and saves of board rows", () => {
    expect(streamEventOf(frame({ l9: { payload: { type: "ping", data: { episode: T1 } } } }), ROOM)).toBeNull();
    expect(streamEventOf(notice({ subkind: "floor", key: "work/a" }), ROOM)).toBeNull();
    const save = (key: string) =>
      frame({ content: `memory updated → ${key}`, l9: { header: { message: { episode: `urn:ioc:mycelium:episode:${ROOM}:knowledge` } } } }, { message_type: "l9_knowledge" });
    expect(streamEventOf(save("work/a"), ROOM)).toBeNull();
    expect(streamEventOf(save("uploads/shot.png"), ROOM)).toMatchObject({ kind: "saved", text: "uploads/shot.png", episode: null });
  });
});

describe("foldEvents", () => {
  const ev = (over: Partial<StreamEvent>): StreamEvent => ({
    id: String(Math.random()),
    at: "2026-10-11T20:57:10Z",
    who: "hub",
    kind: "saved",
    episode: null,
    title: null,
    text: "uploads/a.png",
    subkind: null,
    change: null,
    ref: null,
    assignee: null,
    asked: [],
    mentions: [],
    ...over,
  });

  it("folds the same kind by the same actor in the same minute", () => {
    const lines = foldEvents([ev({}), ev({ text: "uploads/b.png" }), ev({ at: "2026-10-11T20:58:00Z" })]);
    expect(lines).toHaveLength(2);
    expect(lines[0].more).toHaveLength(1);
  });

  it("never folds messages", () => {
    const m = { kind: "message" as const, who: "julia", text: "hi" };
    expect(foldEvents([ev(m), ev(m)])).toHaveLength(2);
  });
});

describe("lanesOf", () => {
  it("gives each thread a lane from its first line to its last", () => {
    const lines = [T1, null, T2, T1, null].map((episode, i) => ({
      event: { episode, id: String(i) } as StreamEvent,
      more: [],
    }));
    const lanes = lanesOf(lines);
    expect(lanes.map(({ episode, column, from, to }) => ({ episode, column, from, to }))).toEqual([
      { episode: T1, column: 0, from: 0, to: 3 },
      { episode: T2, column: 1, from: 2, to: 2 },
    ]);
    // Running at the same time, the two never share a color.
    expect(lanes[0].color).not.toBe(lanes[1].color);
  });

  it("reuses a column once the thread in it has ended", () => {
    const lines = [T1, T1, T2].map((episode, i) => ({ event: { episode, id: String(i) } as StreamEvent, more: [] }));
    expect(lanesOf(lines).map((l) => l.column)).toEqual([0, 0]);
  });
});

describe("dayLabel", () => {
  // Noon local time, so a time zone can't move it to another day.
  const now = new Date(2026, 9, 12, 12, 0);
  const at = (y: number, m: number, d: number) => new Date(y, m, d, 9, 30).toISOString();

  it("says Today and Yesterday for the last two days", () => {
    expect(dayLabel(at(2026, 9, 12), now)).toBe("Today");
    expect(dayLabel(at(2026, 9, 11), now)).toBe("Yesterday");
  });

  it("names the weekday and date further back, adding the year only when it differs", () => {
    const label = dayLabel(at(2026, 7, 27), now);
    expect(label).toMatch(/Thursday/);
    expect(label).toMatch(/27/);
    expect(label).not.toMatch(/2026/);
    expect(dayLabel(at(2025, 7, 27), now)).toMatch(/2025/);
  });

  it("puts two times on the same day under one date", () => {
    expect(dayOf(at(2026, 7, 27))).toBe(dayOf(new Date(2026, 7, 27, 23, 59).toISOString()));
    expect(dayOf(at(2026, 7, 27))).not.toBe(dayOf(at(2026, 7, 28)));
  });
});

describe("matches", () => {
  const msg = streamEventOf(message("mycelium-coder", "@julia done", T1), ROOM)!;
  const base = { kinds: ALL_KINDS, mentioning: null, who: null, where: null };

  it("filters on facts: kind, mention, person and place", () => {
    expect(matches(msg, base)).toBe(true);
    expect(matches(msg, { ...base, kinds: new Set(["board"]) })).toBe(false);
    expect(matches(msg, { ...base, mentioning: "julia" })).toBe(true);
    expect(matches(msg, { ...base, mentioning: "bob" })).toBe(false);
    expect(matches(msg, { ...base, who: "julia" })).toBe(false);
    expect(matches(msg, { ...base, where: "channel" })).toBe(false);
    expect(matches(msg, { ...base, where: T1 })).toBe(true);
  });
});
