import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import { KeymapProvider } from "@/components/keymap-provider";

vi.mock("@/components/current-user", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/current-user")>()),
  useCurrentUser: () => ({ principal: "julia" }),
}));
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
});

describe("a message's hover bar", () => {
  /** Today at `h`:`m`, local time, as the hub would stamp it. */
  const today = (h: number, m: number) => {
    const d = new Date();
    d.setHours(h, m, 0, 0);
    return d.toISOString();
  };

  it("says when, on the first message under a name as on the ones after it", () => {
    const first = event({ id: "m1", messageId: "m1", sender: "builder", content: "on it", at: today(9, 41) });
    const next = event({ id: "m2", messageId: "m2", sender: "builder", content: "done", at: today(9, 43) });
    // From another day, so the time alone would read as today's.
    const old = event({ id: "m3", messageId: "m3", sender: "scout", content: "from before", at: "2025-03-04T15:20:00Z" });
    renderWithSWR(
      <KeymapProvider>
        <FeedRow ev={first} ctx={ctx} />
        <FeedRow ev={next} prev={first} ctx={ctx} />
        <FeedRow ev={old} prev={next} ctx={ctx} />
      </KeymapProvider>,
    );
    for (const [text, time] of [
      ["on it", "09:41"],
      ["done", "09:43"],
      ["from before", /2025/],
    ] as const) {
      const row = screen.getByText(text).closest(".group") as HTMLElement;
      fireEvent.mouseEnter(row);
      expect(within(screen.getByRole("toolbar", { name: "Message actions" })).getByText(time)).toBeInTheDocument();
      fireEvent.mouseLeave(row);
    }
  });
});
