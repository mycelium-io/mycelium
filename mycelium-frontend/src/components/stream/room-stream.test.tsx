// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { layOut } from "@/test/scroll";

const THREAD = "urn:ioc:mycelium:episode:sprint:t1";
const at = (m: number) => `2026-10-11T20:${String(m).padStart(2, "0")}:00Z`;

const history = [
  // A day before everything else, so the log crosses a day.
  { id: "m0", sender_handle: "alice", message_type: "broadcast", created_at: "2026-10-10T20:00:00Z", content: "yesterday's note" },
  {
    id: "n1",
    sender_handle: "system",
    message_type: "l9_exchange",
    created_at: at(1),
    content: JSON.stringify({
      l9: { payload: { type: "notice", data: { subkind: "filed", key: "work/zoom", title: "Zoom and pan", episode: THREAD, by: "chat-buddy" } } },
    }),
  },
  { id: "m1", sender_handle: "alice", message_type: "broadcast", created_at: at(2), content: "morning all" },
  // A file saved in the room's own channel: an event line with no thread.
  {
    id: "k1",
    sender_handle: "system",
    message_type: "l9_knowledge",
    created_at: at(2),
    content: JSON.stringify({ content: "memory updated → uploads/shot.png" }),
  },
  { id: "m2", sender_handle: "builder", message_type: "broadcast", created_at: at(3), episode: THREAD, content: "@bob which preset?\n\nZed or VS Code." },
];

vi.mock("@/lib/api", () => ({
  fetchWireHistory: vi.fn(async () => history),
  fetchUsers: vi.fn(async () => []),
  logFetchError: () => () => {},
}));
// The live feed: a test pushes a frame through what the Stream subscribed with.
const live = vi.hoisted(() => ({ push: (() => {}) as (frame: unknown) => void }));
vi.mock("@/lib/stream-hub", () => ({
  useRoomStream: (_room: string, onFrame: (frame: unknown) => void) => {
    live.push = onFrame;
  },
}));
vi.mock("@/lib/room-data", () => ({
  useRoomThreads: () => new Map([[THREAD, { keys: ["work/zoom"], title: "Zoom and pan" }]]),
  useRoomAgents: () => ({ agents: [] }),
  useRoomRowNames: () => new Map(),
  useRoomVerifierFlags: () => ({ byMessage: new Map(), refresh: () => {} }),
}));
vi.mock("@/components/message-actions", () => ({ MessageActions: () => null }));
vi.mock("@/components/current-user", () => ({ useCurrentUser: () => ({ principal: "bob" }) }));
vi.mock("@/components/message-body", () => ({ MessageBody: ({ content }: { content: string }) => <div>{content}</div> }));

import { RoomStream } from "@/components/stream/room-stream";
import { laneColor } from "@/lib/room-stream";

async function renderStream(onOpenThread = vi.fn()) {
  render(<RoomStream roomName="sprint" onOpenThread={onOpenThread} />);
  await act(async () => {});
  return onOpenThread;
}

/** Make the log 1000px tall in a 400px window and scroll it to `top`. */
function scrollLog(top: number) {
  const el = screen.getByRole("log");
  Object.defineProperty(el, "scrollHeight", { configurable: true, value: 1000 });
  Object.defineProperty(el, "clientHeight", { configurable: true, value: 400 });
  el.scrollTo = vi.fn(({ top: to }: ScrollToOptions) => {
    el.scrollTop = Number(to);
  }) as unknown as typeof el.scrollTo;
  el.scrollTop = top;
  act(() => {
    el.dispatchEvent(new Event("scroll"));
  });
  return el;
}

describe("<RoomStream /> jump to latest", () => {
  beforeEach(() => window.localStorage.clear());

  it("offers no jump at the newest line", async () => {
    await renderStream();
    scrollLog(600);
    expect(screen.queryByRole("button", { name: /Jump to latest/ })).not.toBeInTheDocument();
  });

  it("keeps the reader on the newest line when a tall one lands", async () => {
    await renderStream();
    const box = layOut(screen.getByRole("log"), "[data-line]");
    act(() => {
      live.push({ id: "m9", sender_handle: "alice", message_type: "broadcast", created_at: at(9), content: "a long reply" });
    });
    expect(box.atBottom()).toBe(true);
  });

  it("counts the messages that arrive while you're scrolled up, and jumps back down", async () => {
    await renderStream();
    const log = scrollLog(0);
    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeInTheDocument();

    act(() => {
      live.push({ id: "m9", sender_handle: "alice", message_type: "broadcast", created_at: at(9), content: "back from lunch" });
      // A board change is a line, not a message, so it isn't counted.
      live.push({
        id: "n9",
        sender_handle: "system",
        message_type: "l9_exchange",
        created_at: at(9),
        content: JSON.stringify({
          l9: { payload: { type: "notice", data: { subkind: "claimed", key: "work/zoom", title: "Zoom and pan", episode: THREAD, by: "bob" } } },
        }),
      });
    });
    const jump = screen.getByRole("button", { name: "Jump to latest, 1 new" });
    expect(jump).toHaveTextContent("1 new message");

    await userEvent.click(jump);
    expect(log.scrollTo).toHaveBeenCalledWith({ top: 1000, behavior: "smooth" });
    expect(screen.queryByRole("button", { name: /Jump to latest/ })).not.toBeInTheDocument();
  });
});

describe("<RoomStream />", () => {
  beforeEach(() => window.localStorage.clear());

  it("shows the channel, threads and board changes in one time-ordered log", async () => {
    await renderStream();
    const log = screen.getByRole("log");
    const text = log.textContent ?? "";
    expect(text.indexOf("filed")).toBeLessThan(text.indexOf("morning all"));
    expect(text.indexOf("morning all")).toBeLessThan(text.indexOf("which preset?"));
  });

  it("draws a date line wherever the day changes", async () => {
    await renderStream();
    const dates = screen.getAllByRole("separator");
    // One above the first line, and one where the 10th turns into the 11th.
    expect(dates).toHaveLength(2);
    const text = screen.getByRole("log").textContent ?? "";
    expect(text.indexOf("yesterday's note")).toBeLessThan(text.indexOf(dates[1].textContent ?? ""));
  });

  it("colors an event's icon with its thread's lane, and a channel event's grey", async () => {
    await renderStream();
    // The gutter is hidden from screen readers (the line says it in words).
    const colorOf = (name: string) =>
      screen.getByRole("img", { name, hidden: true }).querySelector("svg")?.getAttribute("style") ?? "";
    // The thread's only lane keeps the thread's own color.
    const lane = document.createElement("span");
    lane.style.color = laneColor(THREAD);
    expect(colorOf("New task")).toContain(lane.style.color);
    expect(colorOf("Memory updated")).toContain("var(--muted-foreground)");
  });

  it("filters to messages that mention you", async () => {
    const user = userEvent.setup();
    await renderStream();
    await user.click(screen.getByRole("button", { name: "@bob" }));
    expect(screen.queryByText("morning all")).not.toBeInTheDocument();
    expect(screen.getByText(/which preset\?/)).toBeInTheDocument();
  });

  it("opens a message in place, and is a stream to read with nowhere to type", async () => {
    const user = userEvent.setup();
    await renderStream();
    await user.click(screen.getByText(/which preset\?/));
    expect(screen.getByText(/Zed or VS Code/)).toBeInTheDocument();
    // Replying happens in the channel or the task's thread, not here.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/Replying in/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Back to the channel/ })).not.toBeInTheDocument();
  });

  it("opens a task's thread from its tag", async () => {
    const user = userEvent.setup();
    const onOpenThread = await renderStream();
    await user.click(screen.getAllByRole("button", { name: "Zoom and pan" })[0]);
    expect(onOpenThread).toHaveBeenCalledWith(THREAD);
  });
});
