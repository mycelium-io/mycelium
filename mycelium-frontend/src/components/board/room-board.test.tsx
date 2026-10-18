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
    renderWithSWR(<RoomBoard roomName="checkout" onOpenThread={onOpenThread} />);

    const asks = await screen.findByRole("region", { name: "Waiting on you" });
    expect(within(asks).getByText(/refund automatically/)).toBeInTheDocument();
    expect(within(asks).getByText("Part of Apple Pay for everyone")).toBeInTheDocument();
    await userEvent.click(within(asks).getByRole("button", { name: "Answer" }));
    expect(onOpenThread).toHaveBeenCalledWith(ep("double"));

    const room = screen.getByRole("region", { name: "In this room" });
    expect(within(room).getByText(/^1 of 4 parts done · led by builder$/)).toBeInTheDocument();
    expect(within(room).getByText("These run side by side.")).toBeInTheDocument();
    // A running part says its latest line; yours says what it waits on.
    expect(within(room).getByText("reviewer: Approved #504.")).toBeInTheDocument();
    expect(within(room).getByText("Starts after Add Apple Pay to checkout")).toBeInTheDocument();
    expect(within(room).getAllByText("you")).not.toHaveLength(0);
    // A lone task someone is on sits with the epics, and says when it went quiet.
    expect(within(room).getByText("Alert us when payments fail")).toBeInTheDocument();
    expect(within(room).getByText("Quiet for 5 hours")).toBeInTheDocument();

    const next = screen.getByRole("region", { name: "Up next" });
    expect(within(next).getByText("Remove the old card form")).toBeInTheDocument();
    expect(within(next).getByText("Starts after Apple Pay for everyone")).toBeInTheDocument();

    // A person's board moves no work: nothing to claim, release or resolve.
    for (const verb of [/claim/i, /release/i, /resolve/i]) {
      expect(screen.queryByRole("button", { name: verb })).not.toBeInTheDocument();
    }
  });

  it("opens a part's thread from the path", async () => {
    board = { epics: [APPLE_PAY], tasks: [] };
    waiting = { handle: "julia", items: [] };
    const onOpenThread = vi.fn();
    renderWithSWR(<RoomBoard roomName="checkout" onOpenThread={onOpenThread} />);
    await userEvent.click(await screen.findByRole("button", { name: /Fix the double charges/ }));
    expect(onOpenThread).toHaveBeenCalledWith(ep("double"));
    expect(screen.queryByRole("region", { name: "Waiting on you" })).not.toBeInTheDocument();
  });

  it("says plainly when nothing is going on", async () => {
    board = { epics: [], tasks: [] };
    waiting = { handle: "julia", items: [] };
    renderWithSWR(<RoomBoard roomName="checkout" />);
    expect(await screen.findByText("Nothing is going on in this room yet")).toBeInTheDocument();
  });
});
