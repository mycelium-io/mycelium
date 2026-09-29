// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
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
    expect(notice).toEqual({
      subkind: "filed",
      key: "work/flip",
      title: "flip reads",
      episode: THREAD,
      by: "aligner",
      kind: "action",
      assignee: "@growth",
      speakers: [],
      released: false,
    });
  });

  it("reads whose turn it is off a floor notice", () => {
    // The one notice about a thread rather than a task: the holder, the handles
    // it gave the floor to, and whether it just opened back up.
    const given = noticeOf(noticeFrame({ subkind: "floor", key: "t3", episode: THREAD, by: "conductor", speakers: "api,sec" }));
    expect(given).toMatchObject({ subkind: "floor", by: "conductor", speakers: ["api", "sec"], released: false });
    const alone = noticeOf(noticeFrame({ subkind: "floor", key: "t3", episode: THREAD, by: "conductor" }));
    expect(alone).toMatchObject({ speakers: [], released: false });
    const opened = noticeOf(noticeFrame({ subkind: "floor", key: "t3", episode: THREAD, by: "conductor", released: "1" }));
    expect(opened).toMatchObject({ speakers: [], released: true });
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
    expect(noticeLabel("blocked", null)).toBe("Blocked");
    expect(noticeLabel("unblocked", null)).toBe("Unblocked");
    expect(noticeLabel("expired", null)).toBe("Expired");
  });
});
