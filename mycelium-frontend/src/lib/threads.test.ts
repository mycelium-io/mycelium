// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  PING_TYPE,
  coalescePings,
  filedLabel,
  isLiveEpisode,
  liveEpisodeUrn,
  pingOf,
  taskCreatedOf,
  threadShortId,
  type Pingable,
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

describe("reading a task-created notice", () => {
  function filedFrame(data: Record<string, unknown>) {
    return {
      l9: {
        header: { kind: "exchange", message: { episode: liveEpisodeUrn(ROOM) } },
        payload: { type: "task_created", data },
      },
    };
  }

  it("carries the task, its title, its own thread, and who filed it", () => {
    // Like a ping, it rides in `live` and names the task it filed in its payload,
    // so a notice can open the same thread the row's own chip does.
    const created = taskCreatedOf(
      filedFrame({ key: "work/flip", title: "flip reads", episode: THREAD, by: "aligner", kind: "action" }),
    );
    expect(created).toEqual({ key: "work/flip", title: "flip reads", episode: THREAD, by: "aligner", kind: "action" });
  });

  it("is not a task-created notice when the payload is a ping", () => {
    expect(taskCreatedOf(pingFrame(THREAD, "risk", "m7"))).toBeNull();
  });

  it("refuses a notice that names no task", () => {
    expect(taskCreatedOf(filedFrame({ title: "no key" }))).toBeNull();
    expect(taskCreatedOf({})).toBeNull();
    expect(taskCreatedOf(null)).toBeNull();
  });

  it("names what was filed by its kind, not always a task", () => {
    expect(filedLabel("decision")).toBe("New decision");
    expect(filedLabel("concern")).toBe("New concern");
    expect(filedLabel("blocked")).toBe("New blocker");
    expect(filedLabel("action")).toBe("New task");
    // An unknown or missing kind falls back to the plain word.
    expect(filedLabel(null)).toBe("New task");
    expect(filedLabel("whatever")).toBe("New task");
  });
});

describe("coalescing a burst of pings", () => {
  const ping = (thread: string, sender: string): Pingable & { id: string; count: number } => ({
    id: `${thread}-${sender}`,
    type: PING_TYPE,
    thread,
    pingSenders: [sender],
    count: 1,
  });
  const said = (id: string): Pingable & { id: string; count: number } => ({
    id,
    type: "broadcast",
    thread: null,
    pingSenders: [],
    count: 0,
  });
  const fold = <T extends Pingable & { count: number }>(rows: T[]) =>
    coalescePings(rows, r => r.count, (latest, count) => ({ ...latest, count }));

  it("turns a busy thread into one line carrying the count", () => {
    const rows = fold([ping(THREAD, "risk"), ping(THREAD, "growth"), ping(THREAD, "risk")]);
    expect(rows).toHaveLength(1);
    expect(rows[0].count).toBe(3);
  });

  it("keeps two active threads apart", () => {
    const other = "urn:ioc:mycelium:episode:atlas:t9";
    const rows = fold([ping(THREAD, "risk"), ping(other, "growth"), ping(THREAD, "risk")]);
    expect(rows.map(r => r.thread)).toEqual([THREAD, other]);
    expect(rows[0].count).toBe(2);
    expect(rows[1].count).toBe(1);
  });

  it("stops at the first thing said in the room", () => {
    // A ping after someone speaks is new activity, not more of the same, and
    // folding it backwards would move a line that has already been read.
    const rows = fold([ping(THREAD, "risk"), said("a1"), ping(THREAD, "risk")]);
    expect(rows.map(r => r.id)).toEqual([`${THREAD}-risk`, "a1", `${THREAD}-risk`]);
  });

  it("leaves a feed with no pings in it exactly as it found it", () => {
    const rows = [said("a1"), said("a2")];
    expect(fold(rows)).toEqual(rows);
  });

  it("collects who wrote, in the order they first did", () => {
    const senders = coalescePings(
      [ping(THREAD, "risk"), ping(THREAD, "growth"), ping(THREAD, "risk")],
      r => r.count,
      (latest, count, who) => ({ ...latest, count, who }),
    ) as (Pingable & { who?: string[] })[];
    expect(senders[0].who).toEqual(["risk", "growth"]);
  });
});
