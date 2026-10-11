// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  applyEvent,
  applyRow,
  chainOf,
  entryHref,
  isInvolved,
  rowFactsOf,
  sortEntries,
  taskEventOf,
  taskIdOf,
  yourMove,
  type Me,
  type TaskEntry,
  type TaskEvent,
} from "@/lib/task-inbox";

const ROOM = "mycelium-general";
const THREAD = `urn:ioc:mycelium:episode:${ROOM}:a8954e53`;
const ME: Me = { handle: "julia", agents: new Set(["mycelium-chat-buddy"]) };

let n = 0;
const at = () => `2026-10-11T20:${String(10 + n).padStart(2, "0")}:00Z`;

function notice(subkind: string, data: Record<string, string> = {}) {
  n += 1;
  return {
    id: `n${n}`,
    room_name: ROOM,
    sender_handle: "system",
    message_type: "l9_exchange",
    created_at: at(),
    content: JSON.stringify({
      l9: { payload: { type: "notice", data: { subkind, key: "work/zoom", title: "Zoom and pan", episode: THREAD, ...data } } },
    }),
  };
}

function message(sender: string, text: string, episode: string | null = THREAD) {
  n += 1;
  return {
    id: `m${n}`,
    room_name: ROOM,
    sender_handle: sender,
    message_type: "l9_exchange",
    created_at: at(),
    episode,
    content: JSON.stringify({ content: text }),
  };
}

function fold(frames: Record<string, unknown>[], me: Me = ME): TaskEntry | undefined {
  let entry: TaskEntry | undefined;
  for (const f of frames) {
    const ev = taskEventOf(f, me.handle);
    if (ev) entry = applyEvent(entry, ev, me);
  }
  return entry;
}

describe("taskEventOf", () => {
  it("reads a board notice as an event on its task", () => {
    const ev = taskEventOf(notice("upstream", { change: "approved", by: "mycelium-reviewer", ref: "o/r#1258" }), "julia");
    expect(ev).toMatchObject({ kind: "upstream", change: "approved", key: "work/zoom", actor: "mycelium-reviewer", ref: "o/r#1258" });
  });

  it("drops the room's channel chatter that doesn't name you", () => {
    expect(taskEventOf(message("alice", "morning all", null), "julia")).toBeNull();
    expect(taskEventOf(message("alice", "@julia one for you", null), "julia")).toMatchObject({ mention: "ask", episode: null });
  });

  it("reads a plain chat frame the same as an exchange", () => {
    const frame = { ...message("alice", ""), message_type: "broadcast", content: "@julia over to you" };
    expect(taskEventOf(frame, "julia")).toMatchObject({ kind: "message", mention: "ask", text: "@julia over to you" });
  });

  it("tells a silent mention from one that asks", () => {
    expect(taskEventOf(message("alice", "ready for @~julia"), "julia")?.mention).toBe("silent");
    expect(taskEventOf(message("alice", "@julia can you look?"), "julia")?.mention).toBe("ask");
    expect(taskEventOf(message("julia", "@julia note to self"), "julia")?.mention).toBeNull();
  });

  it("skips pings and floor notices", () => {
    const ping = {
      ...message("system", ""),
      content: JSON.stringify({ l9: { payload: { type: "ping", data: { episode: THREAD } } } }),
    };
    expect(taskEventOf(ping, "julia")).toBeNull();
    expect(taskEventOf(notice("floor"), "julia")).toBeNull();
  });
});

describe("involvement", () => {
  it("is decided by who filed, holds or is asked, including your own agents", () => {
    expect(isInvolved(fold([notice("claimed", { by: "voice-model" })])!)).toBe(false);
    expect(isInvolved(fold([notice("filed", { by: "mycelium-chat-buddy" })])!)).toBe(true);
    expect(isInvolved(fold([notice("filed", { by: "alice", for: "julia" })])!)).toBe(true);
    expect(isInvolved(fold([message("alice", "thoughts @~julia?")])!)).toBe(true);
    expect(isInvolved(fold([message("julia", "on it")])!)).toBe(true);
  });

  it("can come from the row's own fields", () => {
    const entry = fold([message("voice-model", "PR is up")])!;
    expect(isInvolved(entry)).toBe(false);
    const row = rowFactsOf({
      key: "work/zoom",
      created_by: "mycelium-chat-buddy",
      value: "Zoom and pan images in the upload preview\n\nbody",
      content_text: "A note the search index leads with",
      meta: { status: "open", assignment: "held", owner: "@voice-model" },
    });
    expect(row.title).toBe("Zoom and pan images in the upload preview");
    expect(row.holder).toBe("@voice-model");
    const joined = applyRow(entry, row, ME);
    expect(isInvolved(joined)).toBe(true);
    expect(joined.yours).toBe(true);
  });
});

describe("yourMove", () => {
  it("is ready to merge once approved with CI green, and clears on merge", () => {
    const filed = notice("filed", { by: "mycelium-chat-buddy", for: "voice-model" });
    const ready = fold([filed, notice("upstream", { change: "opened" }), notice("upstream", { change: "approved" }), notice("upstream", { change: "ci_passed" })])!;
    expect(yourMove(ready)).toBe("ready");
    // The newest four steps, with what came before folded into "…".
    expect(chainOf(ready)).toEqual(["…", "PR opened", "approved", "CI green", "ready to merge"]);
    const merged = applyEvent(ready, taskEventOf(notice("upstream", { change: "merged" }), "julia")!, ME);
    expect(yourMove(merged)).toBeNull();
  });

  it("counts CI red as needing you only on your own work", () => {
    const theirs = fold([message("alice", "@~julia fyi"), notice("upstream", { change: "ci_failed" })])!;
    expect(yourMove(theirs)).toBeNull();
    const yours = fold([notice("filed", { by: "julia" }), notice("upstream", { change: "ci_failed" })])!;
    expect(yourMove(yours)).toBe("ci_red");
  });

  it("asks until you answer in the thread", () => {
    const asked = fold([message("mycelium-coder", "@julia which preset?")])!;
    expect(yourMove(asked)).toBe("asks");
    const answered = applyEvent(asked, taskEventOf(message("julia", "Zed"), "julia")!, ME);
    expect(yourMove(answered)).toBeNull();
  });

  it("never asks on a settled task", () => {
    const entry = fold([message("alice", "@julia ok?"), notice("resolved", { by: "alice" })])!;
    expect(yourMove(entry)).toBeNull();
  });
});

describe("the bell's order", () => {
  it("puts questions first, then the rest of what waits on you, then everything else newest first", () => {
    const mk = (id: string, ev: TaskEvent[]): TaskEntry => ev.reduce<TaskEntry | undefined>((e, x) => applyEvent(e, x, ME), undefined)!;
    const ready = mk("a", [
      taskEventOf(notice("filed", { by: "julia", episode: `${THREAD}1` }), "julia")!,
      taskEventOf(notice("upstream", { change: "approved", episode: `${THREAD}1` }), "julia")!,
      taskEventOf(notice("upstream", { change: "ci_passed", episode: `${THREAD}1` }), "julia")!,
    ]);
    const asks = mk("b", [taskEventOf(message("bob", "@julia?", `${THREAD}2`), "julia")!]);
    const quiet = mk("c", [taskEventOf(message("julia", "noted", `${THREAD}3`), "julia")!]);
    const { needsYou, earlier } = sortEntries([quiet, ready, asks]);
    expect(needsYou.map((e) => e.id)).toEqual([asks.id, ready.id]);
    expect(earlier.map((e) => e.id)).toEqual([quiet.id]);
  });

  it("opens a task's thread in its room", () => {
    const entry = fold([message("bob", "@julia?")])!;
    expect(entry.id).toBe(taskIdOf(ROOM, THREAD, null));
    expect(entryHref(entry)).toBe(`/room/${ROOM}?focus=episode%3Aa8954e53`);
  });
});
