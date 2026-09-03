// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  byActor,
  byDay,
  dayKey,
  daysEnding,
  digest,
  heatLevel,
  projectActivity,
  shiftDay,
  streaks,
  today,
  weekdayIndex,
  type ActivityEvent,
} from "@/lib/board/activity";
import type { EpisodeSummary, Memory, RoomMessage } from "@/lib/api";

const event = (at: string, actor: string, over: Partial<ActivityEvent> = {}): ActivityEvent => ({
  id: `${actor}:${at}`,
  at,
  actor,
  actorKind: "human",
  action: "posted",
  title: "something",
  source: "test",
  ...over,
});

describe("calendar", () => {
  it("puts an instant on the day it falls on in the reader's zone, not UTC's", () => {
    // 03:30 UTC is still the previous evening in Los Angeles and already
    // mid-morning in Tokyo: one instant, three different days.
    const at = "2026-08-22T03:30:00Z";
    expect(dayKey(at, "UTC")).toBe("2026-08-22");
    expect(dayKey(at, "America/Los_Angeles")).toBe("2026-08-21");
    expect(dayKey(at, "Asia/Tokyo")).toBe("2026-08-22");
  });

  it("survives a zone changing offset, because a day is calendar arithmetic", () => {
    // The clocks go back in Europe on 2026-10-25; adding a day is still a day.
    expect(shiftDay("2026-10-24", 1)).toBe("2026-10-25");
    expect(shiftDay("2026-10-25", 1)).toBe("2026-10-26");
    expect(shiftDay("2026-03-01", -1)).toBe("2026-02-28");
    expect(shiftDay("2026-01-01", -1)).toBe("2025-12-31");
  });

  it("falls back to the host zone rather than blanking on an unknown one", () => {
    expect(dayKey("2026-08-22T12:00:00Z", "Mars/Olympus")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("returns null for an unparseable instant", () => {
    expect(dayKey("not a date", "UTC")).toBeNull();
  });

  it("counts weeks from Monday", () => {
    expect(weekdayIndex("2026-08-17")).toBe(0); // Monday
    expect(weekdayIndex("2026-08-23")).toBe(6); // Sunday
  });

  it("lists a window of days oldest first, ending on the day given", () => {
    expect(daysEnding("2026-08-22", 3)).toEqual(["2026-08-20", "2026-08-21", "2026-08-22"]);
  });

  it("reads today in the requested zone", () => {
    const noon = Date.parse("2026-08-22T12:00:00Z");
    expect(today("UTC", noon)).toBe("2026-08-22");
    expect(today("Pacific/Kiritimati", noon)).toBe("2026-08-23");
  });
});

describe("projectActivity", () => {
  const base = {
    room: "atlas",
    messages: [] as RoomMessage[],
    memories: [] as Memory[],
    episodes: [] as EpisodeSummary[],
    agentHandles: ["growth", "risk"],
  };

  it("attributes chat to its sender and knows an agent from a person", () => {
    const events = projectActivity({
      ...base,
      messages: [
        { id: "1", message_type: "broadcast", sender_handle: "growth", content: "dual-write is live", created_at: "2026-08-22T10:00:00Z" },
        { id: "2", message_type: "broadcast", sender_handle: "julia", content: "nice", created_at: "2026-08-22T10:05:00Z" },
      ],
    });
    expect(events.map(e => [e.actor, e.actorKind, e.action])).toEqual([
      ["julia", "human", "posted"],
      ["growth", "agent", "posted"],
    ]);
  });

  it("names an engine apart from the agents", () => {
    const events = projectActivity({
      ...base,
      messages: [{ id: "1", message_type: "broadcast", sender_handle: "aligner", content: "standing offer", created_at: "2026-08-22T10:00:00Z" }],
    });
    expect(events[0].actorKind).toBe("engine");
  });

  it("reads a coordination payload by type instead of printing its JSON", () => {
    const events = projectActivity({
      ...base,
      messages: [
        {
          id: "1",
          message_type: "coordination_tick",
          sender_handle: "aligner",
          content: JSON.stringify({ payload: { round: 4, participant_id: "risk", action: "accept" } }),
          created_at: "2026-08-22T10:00:00Z",
        },
      ],
    });
    // The line is the shared summarizer's (lib/room-events.ts): the log adopts
    // what the channel would print rather than deriving its own.
    expect(events[0]).toMatchObject({ action: "negotiated", title: "Round 4: risk → accept" });
    expect(events[0].title).not.toContain("{");
  });

  it("doesn't log the same work twice from the wire and the store", () => {
    const events = projectActivity({
      ...base,
      messages: [
        { id: "1", message_type: "memory_changed", sender_handle: "growth", content: "{}", created_at: "2026-08-22T10:00:00Z" },
        { id: "2", message_type: "coordination_consensus", sender_handle: "aligner", content: "{}", created_at: "2026-08-22T10:01:00Z" },
      ],
      memories: [
        { key: "decisions/cutover", value: "phased", version: 2, created_by: "aligner", updated_by: "growth", updated_at: "2026-08-22T10:00:00Z" },
      ],
    });
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ actor: "growth", action: "revised", title: "decisions/cutover" });
  });

  it("drops anything it can't attribute or timestamp", () => {
    const events = projectActivity({
      ...base,
      messages: [
        { id: "1", message_type: "broadcast", content: "who said this?", created_at: "2026-08-22T10:00:00Z" },
        { id: "2", message_type: "broadcast", sender_handle: "julia", content: "when?" },
      ],
    });
    expect(events).toHaveLength(0);
  });
});

describe("buckets", () => {
  const events = [
    event("2026-08-22T10:00:00Z", "julia"),
    event("2026-08-22T11:00:00Z", "growth"),
    event("2026-08-21T10:00:00Z", "julia"),
    event("2026-08-19T10:00:00Z", "julia"),
  ];

  it("buckets by day in the given zone", () => {
    const days = byDay(events, "UTC");
    expect([...days.keys()].sort()).toEqual(["2026-08-19", "2026-08-21", "2026-08-22"]);
    expect(days.get("2026-08-22")).toHaveLength(2);
  });

  it("lanes actors busiest first", () => {
    expect(byActor(events).map(l => [l.actor, l.events.length])).toEqual([
      ["julia", 3],
      ["growth", 1],
    ]);
  });

  it("counts a streak back from today, and tolerates a day that hasn't started", () => {
    const days = byDay(events, "UTC");
    // 22nd and 21st are active, the 20th is not.
    expect(streaks(days, "2026-08-22").current).toBe(2);
    // Nothing logged on the 23rd yet, so the run through the 22nd still counts.
    expect(streaks(days, "2026-08-23").current).toBe(2);
    // Two clear days breaks it.
    expect(streaks(days, "2026-08-24").current).toBe(0);
  });

  it("remembers the longest run, wherever it sits", () => {
    expect(streaks(byDay(events, "UTC"), "2026-08-22").longest).toBe(2);
  });

  it("sums a range into a digest", () => {
    const summary = digest(byDay(events, "UTC"), "2026-08-19", "2026-08-22");
    expect(summary.events).toHaveLength(4);
    expect(summary.activeDays).toBe(3);
    expect(summary.actors[0].actor).toBe("julia");
    expect(summary.byAction).toEqual([{ action: "posted", count: 4 }]);
  });

  it("steps heat in five", () => {
    expect([0, 1, 3, 7, 20].map(heatLevel)).toEqual([0, 1, 2, 3, 4]);
  });
});
