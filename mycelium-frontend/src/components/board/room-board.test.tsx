// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The board for people: what is waiting on you, the epics as paths, and what
// is up next, drawn from what the hub works out. No row actions.

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithSWR } from "@/test/swr";
import { describe, expect, it, vi } from "vitest";
import type { BoardPart, BoardRead, WaitingRead } from "@/lib/api";

const ep = (id: string) => `urn:ioc:mycelium:episode:checkout:${id}`;
const AN_HOUR_AGO = new Date(Date.now() - 60 * 60 * 1000).toISOString();
const HOURS_AGO = new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString();

const part = (key: string, title: string, state: BoardPart["state"], more: Partial<BoardPart> = {}): BoardPart => ({
  key,
  title,
  state,
  episode: ep(key.split("/")[1]),
  waiting_on: [],
  parts: 0,
  parts_done: 0,
  ...more,
});

let board: BoardRead = { epics: [], tasks: [] };
let waiting: WaitingRead = { handle: "julia", items: [] };

vi.mock("@/lib/api", () => ({
  logFetchError: () => () => undefined,
  fetchRoomBoard: vi.fn(async () => board),
  fetchWaiting: vi.fn(async () => waiting),
  fetchRoomAgents: vi.fn().mockResolvedValue([{ handle: "builder", adapter: "claude_code" }]),
  fetchRoomMembers: vi.fn().mockResolvedValue({ members: [], floors: [] }),
  fetchRoomPeople: vi.fn().mockResolvedValue({ people: [], agents: [], engines: [], others: [] }),
  createTask: vi.fn(),
  writeFields: vi.fn(),
}));
vi.mock("@/lib/stream-hub", () => ({ useRoomStream: vi.fn() }));
vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia" }),
  usePrincipal: () => "julia",
}));
vi.mock("@/components/start-swarm-dialog", () => ({ StartSwarmDialog: () => null }));

const { RoomBoard } = await import("./room-board");

const APPLE_PAY = {
  ...part("work/apple-pay", "Apple Pay for everyone", "working", { holder: "builder", parts: 4, parts_done: 1 }),
  lead: "builder",
  done: 1,
  total: 4,
  steps: [["work/stripe"], ["work/double", "work/checkout"], ["work/iphone"]],
  path: [
    part("work/stripe", "Move card payments to Stripe", "done", { holder: null }),
    part("work/double", "Fix the double charges", "working", {
      holder: "builder",
      latest: { sender: "reviewer", text: "Approved #504.", at: AN_HOUR_AGO },
    }),
    part("work/checkout", "Add Apple Pay to checkout", "working", {
      holder: "builder",
      latest: { sender: "builder", text: "Opened #502.", at: AN_HOUR_AGO },
    }),
    part("work/iphone", "Test it on a real iPhone", "waiting", {
      assignee: "julia",
      waiting_on: ["work/checkout"],
    }),
  ],
};

describe("<RoomBoard />", () => {
  it("draws what is waiting on you, the epics as paths, the running tasks and what is up next", async () => {
    board = {
      epics: [APPLE_PAY],
      tasks: [
        part("work/alerts", "Alert us when payments fail", "working", {
          holder: "builder",
          latest: { sender: "builder", text: "Wired to on-call.", at: HOURS_AGO },
        }),
        part("work/old-form", "Remove the old card form", "waiting", { waiting_on: ["work/apple-pay"] }),
      ],
    };
    waiting = {
      handle: "julia",
      items: [
        {
          kind: "ask",
          key: "work/double",
          title: "Fix the double charges",
          episode: ep("double"),
          epic: "work/apple-pay",
          epic_title: "Apple Pay for everyone",
          sender: "builder",
          text: "Double charges: refund automatically, or send to support first?",
          count: 1,
        },
      ],
    };
    const onOpenThread = vi.fn();
    const { container } = renderWithSWR(<RoomBoard roomName="checkout" onOpenThread={onOpenThread} />);
    const row = (key: string) => container.querySelector<HTMLElement>(`[data-board-row="${key}"]`)!;

    // The line that says what's going on, before any of the rows.
    expect(
      await screen.findByText("1 thing needs you. 3 tasks are being worked on. 1 is up next."),
    ).toBeInTheDocument();

    const asks = await screen.findByRole("region", { name: "Waiting on you" });
    // The same shape as any row: the task as the title, the words that ask you as the line.
    expect(within(asks).getByText("Fix the double charges")).toBeInTheDocument();
    expect(within(asks).getByText(/refund automatically/)).toBeInTheDocument();
    expect(within(asks).getByText("Asks you")).toBeInTheDocument();
    // The row is what opens it: there is no button to press on it.
    expect(within(asks).queryByRole("button", { name: "Answer" })).not.toBeInTheDocument();
    await userEvent.click(within(asks).getByText(/refund automatically/));
    expect(onOpenThread).toHaveBeenCalledWith(ep("double"));

    const room = screen.getByRole("region", { name: "In this room" });
    // Progress said once, and the epic's line is the newest from its parts.
    expect(within(row("work/apple-pay")).getByText("1 of 4 done")).toBeInTheDocument();
    expect(within(row("work/apple-pay")).getByText("reviewer: Approved #504.")).toBeInTheDocument();
    expect(row("work/checkout").querySelector("[title]")?.getAttribute("title")).toBe(
      "Runs at the same time as Fix the double charges",
    );
    // Parts in path order, numbered by step: two that run side by side share one.
    expect(within(row("work/double")).getByText("2")).toBeInTheDocument();
    expect(within(row("work/checkout")).getByText("2")).toBeInTheDocument();
    expect(within(row("work/iphone")).getByText("3")).toBeInTheDocument();
    // A running part says its latest line; yours says what it waits on.
    expect(within(row("work/double")).getByText("reviewer: Approved #504.")).toBeInTheDocument();
    expect(within(row("work/double")).getByText("Working")).toBeInTheDocument();
    expect(within(row("work/iphone")).getByText("Starts after Add Apple Pay to checkout")).toBeInTheDocument();
    expect(within(row("work/iphone")).getByText("you")).toBeInTheDocument();
    // A lone task someone is on sits with the epics, and says when it went quiet.
    expect(within(room).getByText("Alert us when payments fail")).toBeInTheDocument();
    expect(within(row("work/alerts")).getByText("quiet 5h")).toBeInTheDocument();

    const next = screen.getByRole("region", { name: "Up next" });
    expect(within(next).getByText("Remove the old card form")).toBeInTheDocument();
    expect(within(next).getByText("Starts after Apple Pay for everyone")).toBeInTheDocument();
    expect(within(next).getByText("nobody yet")).toBeInTheDocument();

    // A person's board moves no work: nothing to claim, release or resolve.
    for (const verb of [/claim/i, /release/i, /resolve/i]) {
      expect(screen.queryByRole("button", { name: verb })).not.toBeInTheDocument();
    }
  });

  it("opens a part's thread from its row, and moves between rows with j and k", async () => {
    board = { epics: [APPLE_PAY], tasks: [] };
    waiting = { handle: "julia", items: [] };
    const onOpenThread = vi.fn();
    const { container } = renderWithSWR(<RoomBoard roomName="checkout" onOpenThread={onOpenThread} />);
    await userEvent.click(await screen.findByText("Fix the double charges"));
    expect(onOpenThread).toHaveBeenCalledWith(ep("double"));
    expect(screen.queryByRole("region", { name: "Waiting on you" })).not.toBeInTheDocument();

    await userEvent.keyboard("j");
    expect(document.activeElement).toBe(container.querySelector('[data-board-row="work/checkout"]'));
    await userEvent.keyboard("k");
    expect(document.activeElement).toBe(container.querySelector('[data-board-row="work/double"]'));
  });

  it("shows a task that's waiting on you there, and not again below", async () => {
    board = {
      epics: [],
      tasks: [part("work/alerts", "Alert us when payments fail", "working", { holder: "julia" })],
    };
    waiting = {
      handle: "julia",
      items: [{ kind: "task", key: "work/alerts", title: "Alert us when payments fail", episode: ep("alerts"), count: 1 }],
    };
    renderWithSWR(<RoomBoard roomName="checkout" />);
    const asks = await screen.findByRole("region", { name: "Waiting on you" });
    expect(within(asks).getByText("Alert us when payments fail")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "In this room" })).not.toBeInTheDocument();
  });

  it("says plainly when nothing is going on", async () => {
    board = { epics: [], tasks: [] };
    waiting = { handle: "julia", items: [] };
    renderWithSWR(<RoomBoard roomName="checkout" />);
    expect(await screen.findByText("Nothing is going on in this room yet")).toBeInTheDocument();
    expect(screen.getByText("Hand something off above, and an agent will pick it up.")).toBeInTheDocument();
  });
});
