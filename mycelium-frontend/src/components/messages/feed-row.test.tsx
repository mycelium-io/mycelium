import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Event } from "@/lib/room-events";
import { NOTICE_TYPE, PING_TYPE } from "@/lib/threads";
import { FeedRow, type FeedContext } from "./feed-row";

const AT = "2026-10-18T20:30:00.000Z";
const THREAD = "urn:ioc:mycelium:episode:stick-fighter:a1b2c3d4";

function event(over: Partial<Event>): Event {
  return {
    id: "e",
    messageId: null,
    wireId: null,
    type: "broadcast",
    content: "",
    sender: "system",
    recipient: null,
    time: "20:30:00",
    at: AT,
    episode: null,
    amends: null,
    edited: false,
    thread: null,
    pingSenders: [],
    conductor: null,
    raw: {},
    ...over,
  };
}

const ctx: FeedContext = {
  roomName: "stick-fighter",
  agentHandles: new Set(),
  engineHandles: new Set(),
  agentTags: new Map(),
  agentOwners: new Map(),
  threads: new Map([[THREAD, { title: "Jumps" } as never]]),
  rowNames: new Map(),
  flagsByMessage: new Map(),
  refreshFlags: () => {},
  onOpenThread: () => {},
};

describe("the chat's status rows", () => {
  it("draw who or what, the task, the detail and the time in the same columns", () => {
    const said = event({ sender: "stick-planner", content: "I approve the jump arc" });
    const ping = event({ id: "p", type: PING_TYPE, thread: THREAD, pingSenders: ["stick-planner"] });
    const merged = event({
      id: "n",
      type: NOTICE_TYPE,
      content: "Jumps",
      thread: THREAD,
      raw: { subkind: "upstream", change: "merged", ref: "juliarvalenti/stick-fighter#12" },
    });
    render(
      <div>
        <FeedRow ev={ping} ctx={ctx} pingLine={{ said, quote: "I approve the jump arc", count: 1 }} />
        <FeedRow ev={merged} prev={ping} ctx={ctx} />
      </div>,
    );

    const rows = document.querySelectorAll("[data-system-notice]");
    expect(rows).toHaveLength(2);
    // No "in" on one row and not the other: the task column says where.
    expect(screen.queryByText("in")).toBeNull();
    // The task sits in a column of one width on both rows, so both start together.
    const tasks = screen.getAllByText("Jumps").map((t) => t.closest("button")?.parentElement?.className);
    expect(tasks).toHaveLength(2);
    expect(tasks[0]).toBe(tasks[1]);
    expect(tasks[0]).toContain("w-1/3");
    // Every row says when, even when the row above says the same.
    for (const row of rows) expect(row.querySelector("time, .tabular")).not.toBeNull();
    expect(screen.getByText("I approve the jump arc")).toBeInTheDocument();
    expect(screen.getByText("juliarvalenti/stick-fighter#12")).toBeInTheDocument();
  });

  it("draw no task column, not an empty one, for a line about no task", () => {
    const joined = event({ type: "coordination_join", raw: { handle: "scout" } });
    const inThread = event({ id: "j2", type: "coordination_join", raw: { handle: "scout", episode: THREAD } });
    render(
      <div>
        <FeedRow ev={joined} ctx={ctx} />
        <FeedRow ev={inThread} prev={joined} ctx={ctx} />
      </div>,
    );

    const [room, thread] = document.querySelectorAll("[data-system-notice]");
    // The room join: the name, then "joined" right after it.
    expect(room.querySelector(".w-1\\/3")).toBeNull();
    expect(room.textContent).toContain("joined");
    // A join into a thread still has its task column.
    expect(thread.querySelector(".w-1\\/3")).not.toBeNull();
  });

  it("name a finished run by its task, not its thread's id", () => {
    const done = event({
      id: "c",
      type: "coordination_consensus",
      raw: { episode: THREAD, outcome: "resolved", protocol: "concord", steps: 4 },
    });
    render(<FeedRow ev={done} ctx={ctx} />);
    expect(screen.getByRole("button", { name: "Open thread a1b2c3d4" })).toHaveTextContent("Jumps");
    expect(screen.queryByText("a1b2c3d4")).toBeNull();
    expect(screen.getByText("concord flow, 4 steps")).toBeInTheDocument();
  });
});
