// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// A board row and the thread its coordination happens in are the same object,
// so opening the thread is the row opened — not a second surface to find.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchMemories = vi.fn();

vi.mock("@/lib/api", () => ({
  logFetchError: () => () => undefined,
  fetchRoom: vi.fn().mockResolvedValue({ name: "atlas", title: "Atlas" }),
  fetchEpisodes: vi.fn().mockResolvedValue([]),
  fetchMemories: (...args: unknown[]) => fetchMemories(...args),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchRoomMembers: vi.fn().mockResolvedValue([]),
  fetchMessages: vi.fn().mockResolvedValue({ messages: [] }),
  fetchRoomStatus: vi.fn().mockResolvedValue({ room: "atlas", field: "upstream", providers: [], refs: [], rows: {}, refreshing: false }),
  writeFields: vi.fn(),
  writeLease: vi.fn(),
}));

vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia" }),
}));

vi.mock("@/components/notifications-provider", () => ({
  useNotifications: () => ({ settings: { soundEnabled: false, soundVolume: 0 } }),
}));

import { ThreadChip } from "@/components/board/board-bits";
import { RoomBoard } from "@/components/board/room-board";
import type { LiveItem } from "@/lib/board/item";

const THREAD = "urn:ioc:mycelium:episode:atlas:t3aa11bb";

const row = (fields: Record<string, unknown>): LiveItem => ({
  id: "memory:work/flip",
  title: "flip reads behind a flag",
  source: { kind: "memory", label: "work/flip" },
  fields,
});

describe("<ThreadChip />", () => {
  it("opens the row's thread by URN", async () => {
    const onOpen = vi.fn();
    render(<ThreadChip item={row({ episode: THREAD, thread: "t3aa11bb" })} onOpen={onOpen} />);
    await userEvent.click(screen.getByRole("button", { name: "Open thread t3aa11bb" }));
    expect(onOpen).toHaveBeenCalledWith(THREAD);
  });

  it("offers nothing on a row with no episode at all", () => {
    // Every board row is minted a thread on create, so this is a legacy row from
    // before threading — until the backfill reaches it, the chip stays absent
    // rather than pointing at a thread that is not there.
    const { container } = render(<ThreadChip item={row({ status: "open" })} onOpen={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("does not draw the room's own channel as a thread", () => {
    const live = "urn:ioc:mycelium:episode:atlas:live";
    const { container } = render(<ThreadChip item={row({ episode: live })} onOpen={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("counts the thread only where it has said something", async () => {
    const onOpen = vi.fn();
    const { rerender } = render(<ThreadChip item={row({ episode: THREAD, rounds: 6 })} onOpen={onOpen} />);
    expect(screen.getByRole("button", { name: "Open thread t3aa11bb" })).toHaveTextContent("t3aa11bb · 6");
    // "0 messages" would read as a claim about a conversation nobody has had.
    rerender(<ThreadChip item={row({ episode: THREAD, rounds: 0 })} onOpen={onOpen} />);
    expect(screen.getByRole("button", { name: "Open thread t3aa11bb" })).toHaveTextContent("t3aa11bb");
    expect(screen.getByRole("button", { name: "Open thread t3aa11bb" })).not.toHaveTextContent("· 0");
  });

  it("reads as a plain label where nothing is listening", () => {
    render(<ThreadChip item={row({ episode: THREAD })} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("t3aa11bb")).toBeInTheDocument();
  });
});

const bound = {
  key: "work/flip-reads-behind-a-flag",
  value: { title: "flip reads behind a flag", status: "open" },
  version: 1,
  created_by: "aligner",
  updated_at: "2026-08-04T10:00:00+00:00",
  episode: THREAD,
};

/** A legacy row from before threading: no episode yet, until the backfill mints one. */
const unbound = { ...bound, key: "work/cache-sweep", value: { title: "cache sweep", status: "open" }, episode: null };

describe("<RoomBoard /> thread affordance", () => {
  beforeEach(() => {
    fetchMemories.mockReset().mockResolvedValue([bound]);
    vi.stubGlobal("EventSource", class { close() {} addEventListener() {} });
  });

  it("says why a row has no thread rather than opening some other conversation", async () => {
    // A task is minted a thread on create, so a row without one is a legacy gap
    // the backfill has not reached — the surface refuses in the terms `board
    // messages` refuses in rather than falling back to the room, which would show
    // a different conversation than the one asked for.
    fetchMemories.mockResolvedValue([unbound]);
    const onOpenThread = vi.fn();
    renderWithSWR(<RoomBoard roomName="atlas" onOpenThread={onOpenThread} />);
    await screen.findByText("cache sweep");

    await userEvent.keyboard("j");
    await userEvent.keyboard("t");
    expect(onOpenThread).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/a thread belongs to a task; this row is in another namespace/),
    ).toBeInTheDocument();
  });

  it("opens the selected row's thread on `t`", async () => {
    const onOpenThread = vi.fn();
    renderWithSWR(<RoomBoard roomName="atlas" onOpenThread={onOpenThread} />);
    const chip = await screen.findByRole("button", { name: "Open thread t3aa11bb" });

    // Select the row the way the keyboard does, then reach its thread from the
    // caret — the board is keyboard-first and the thread is one of its verbs.
    await userEvent.keyboard("j");
    await userEvent.keyboard("t");
    await waitFor(() => expect(onOpenThread).toHaveBeenCalledWith(THREAD));

    // And by pointer, from the row itself.
    onOpenThread.mockClear();
    await userEvent.click(chip);
    expect(onOpenThread).toHaveBeenCalledWith(THREAD);
  });
});
