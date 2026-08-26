// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  ACTIVITY_WINDOW_MS,
  coalesceActivity,
  isLiveEpisode,
  liveEpisodeUrn,
  noticeLabel,
  noticeOf,
  pingOf,
  threadShortId,
} from "@/lib/threads";

const ROOM = "atlas";
const THREAD = "urn:ioc:mycelium:episode:atlas:t3aa11bb";

function pingFrame(episode: string, sender?: string, message?: string) {
  return {
    l9: {
      header: { kind: "exchange", message: { episode: liveEpisodeUrn(ROOM) } },
      payload: { type: "ping", data: { episode, ...(sender ? { sender } : {}), ...(message ? { message } : {}) } },
    },
  };
}

describe("the room, and the threads inside it", () => {
  it("reads a message with no episode as the room's own", () => {
    // Rows written before threading carry none. Reading those as a thread would
    // empty the channel of its own history.
    expect(isLiveEpisode(ROOM, null)).toBe(true);
    expect(isLiveEpisode(ROOM, undefined)).toBe(true);
  });

  it("reads the live URN as the room, and anything else as a thread", () => {
    expect(isLiveEpisode(ROOM, liveEpisodeUrn(ROOM))).toBe(true);
    expect(isLiveEpisode(ROOM, THREAD)).toBe(false);
  });

  it("does not mistake another room's live URN for this room's", () => {
    expect(isLiveEpisode(ROOM, liveEpisodeUrn("pricing"))).toBe(false);
  });

  it("names a thread by the tail of its URN, and the room by nothing", () => {
    expect(threadShortId(THREAD)).toBe("t3aa11bb");
    expect(threadShortId(liveEpisodeUrn(ROOM))).toBeNull();
    expect(threadShortId(null)).toBeNull();
  });
});

describe("reading a ping", () => {
  it("takes the thread from the payload, never from the frame's own episode", () => {
    // A ping rides in `live` — that is what makes it reach the room — so the
    // two answer different questions and confusing them would point every ping
    // at the room it was raised in.
    const ping = pingOf(pingFrame(THREAD, "risk", "m7"));
    expect(ping).toEqual({ episode: THREAD, sender: "risk", message: "m7" });
  });

  it("is not a ping when the payload is a message", () => {
    const frame = { content: "hello", l9: { payload: { type: "message", data: {} } } };
    expect(pingOf(frame)).toBeNull();
  });

  it("refuses a ping that names no thread rather than inventing one", () => {
    expect(pingOf({ l9: { payload: { type: "ping", data: {} } } })).toBeNull();
  });

  it("survives a frame with no envelope at all", () => {
    expect(pingOf({})).toBeNull();
    expect(pingOf(null)).toBeNull();
  });
});

describe("reading a notice", () => {
  function noticeFrame(data: Record<string, unknown>) {
    return {
      l9: {
        header: { kind: "exchange", message: { episode: liveEpisodeUrn(ROOM) } },
        payload: { type: "notice", data },
      },
    };
  }

  it("carries what happened, to which task, its thread, and who moved it", () => {
    // Like a ping, it rides in `live` and names the task in its payload, so a
    // notice can open the same thread the row's own chip does. `for` (who a
    // filing is for) reads back as `assignee`.
    const notice = noticeOf(
      noticeFrame({ subkind: "filed", key: "work/flip", title: "flip reads", episode: THREAD, by: "aligner", kind: "action", for: "@growth" }),
    );
    expect(notice).toEqual({ subkind: "filed", key: "work/flip", title: "flip reads", episode: THREAD, by: "aligner", kind: "action", assignee: "@growth" });
  });

  it("reads a lease event with no board kind", () => {
    const notice = noticeOf(noticeFrame({ subkind: "claimed", key: "work/flip", by: "growth" }));
    expect(notice).toMatchObject({ subkind: "claimed", key: "work/flip", by: "growth", kind: null });
  });

  it("is not a notice when the payload is a ping", () => {
    expect(noticeOf(pingFrame(THREAD, "risk", "m7"))).toBeNull();
  });

  it("refuses a notice that names no task or no subkind", () => {
    expect(noticeOf(noticeFrame({ subkind: "filed" }))).toBeNull();
    expect(noticeOf(noticeFrame({ key: "work/flip" }))).toBeNull();
    expect(noticeOf({})).toBeNull();
    expect(noticeOf(null)).toBeNull();
  });

  it("labels a filing by its kind, and a lease event by what happened", () => {
    expect(noticeLabel("filed", "decision")).toBe("New decision");
    expect(noticeLabel("filed", "blocked")).toBe("New blocker");
    expect(noticeLabel("filed", "action")).toBe("New task");
    expect(noticeLabel("filed", null)).toBe("New task");
    expect(noticeLabel("claimed", null)).toBe("Claimed");
    expect(noticeLabel("released", null)).toBe("Released");
    expect(noticeLabel("resolved", null)).toBe("Resolved");
  });
});

describe("condensing a subject's activity", () => {
  const TASK = "work/882-login-aligns-identity";
  const OTHER = "work/886-activity-feed-coalescing";
  const T0 = Date.parse("2026-08-26T00:00:00Z");

  interface Row {
    id: string;
    subject: string | null;
    at: string;
    members?: Row[];
  }
  const row = (id: string, subject: string | null, offsetMs = 0): Row => ({
    id,
    subject,
    at: new Date(T0 + offsetMs).toISOString(),
  });
  const said = (id: string, offsetMs = 0): Row => row(id, null, offsetMs);
  const fold = (rows: Row[], windowMs?: number) =>
    coalesceActivity(rows, r => r.subject, members => ({ ...members[0], members }), windowMs);

  it("turns a burst about one task into a single block", () => {
    const rows = fold([row("a", TASK), row("b", TASK, 1000), row("c", TASK, 2000)]);
    expect(rows).toHaveLength(1);
    expect(rows[0].members?.map(m => m.id)).toEqual(["a", "b", "c"]);
  });

  it("folds a ping, a notice and a memory push about the same task into one", () => {
    // The three ways the room says a task moved. Printed separately they read
    // as three events; they are one.
    const rows = fold([row("notice", TASK), row("knowledge", TASK, 500), row("ping", TASK, 900)]);
    expect(rows).toHaveLength(1);
    expect(rows[0].members).toHaveLength(3);
  });

  it("keeps two active subjects apart", () => {
    const rows = fold([row("a", TASK), row("b", OTHER, 100), row("c", TASK, 200)]);
    expect(rows.map(r => r.subject)).toEqual([TASK, OTHER]);
    expect(rows[0].members).toHaveLength(2);
    expect(rows[1].members).toBeUndefined();
  });

  it("keeps folding across what is said in between", () => {
    // The limitation this replaces: the old ping-only coalesce gave up the
    // moment anything else was said, so a busy thread and a talkative room
    // produced exactly the alternating feed the fold exists to prevent.
    const rows = fold([row("a", TASK), said("m1", 100), row("b", TASK, 200)]);
    expect(rows.map(r => r.id)).toEqual(["a", "m1"]);
    expect(rows[0].members?.map(m => m.id)).toEqual(["a", "b"]);
  });

  it("grows the block where it started rather than moving it down the feed", () => {
    // Folding forward would move a line the reader has already passed.
    const rows = fold([row("a", TASK), said("m1", 100), said("m2", 200), row("b", TASK, 300)]);
    expect(rows.map(r => r.id)).toEqual(["a", "m1", "m2"]);
  });

  it("opens a new block once the window has closed", () => {
    // A subject that stays busy keeps saying so — at most one line per window.
    const rows = fold([
      row("a", TASK),
      row("b", TASK, ACTIVITY_WINDOW_MS - 1),
      row("c", TASK, ACTIVITY_WINDOW_MS + 1),
    ]);
    expect(rows.map(r => r.id)).toEqual(["a", "c"]);
    expect(rows[0].members?.map(m => m.id)).toEqual(["a", "b"]);
  });

  it("measures the window from the block's first event, not its last", () => {
    // A sliding gap would let a steadily busy task stay one block for hours,
    // so genuinely new activity would only ever change a number further up.
    const rows = fold(
      [row("a", TASK), row("b", TASK, 60), row("c", TASK, 120), row("d", TASK, 180)],
      100,
    );
    expect(rows.map(r => r.id)).toEqual(["a", "c"]);
  });

  it("hands the merge every member, oldest first, so nothing is lost", () => {
    const rows = fold([row("a", TASK), row("b", TASK, 10), row("c", TASK, 20)]);
    expect(rows[0].members?.map(m => m.at)).toEqual(
      ["a", "b", "c"].map((_, i) => new Date(T0 + i * 10).toISOString()),
    );
  });

  it("passes a subject that moved once through untouched", () => {
    const only = row("a", TASK);
    expect(fold([only, said("m1", 10)])[0]).toBe(only);
  });

  it("leaves a feed with no activity in it exactly as it found it", () => {
    const rows = [said("m1"), said("m2", 10)];
    expect(fold(rows)).toEqual(rows);
  });
});
