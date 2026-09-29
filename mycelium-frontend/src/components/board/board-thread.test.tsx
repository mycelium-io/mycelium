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
  fetchRoomMembers: vi.fn().mockResolvedValue({ members: [], floors: [] }),
  fetchMessages: vi.fn().mockResolvedValue({ messages: [] }),
  fetchRoomStatus: vi.fn().mockResolvedValue({ room: "atlas", field: "upstream", providers: [], refs: [], rows: {}, refreshing: false }),
  writeFields: vi.fn(),
  writeAssignment: vi.fn(),
}));

vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia" }),
}));

vi.mock("@/components/notifications-provider", () => ({
  useNotifications: () => ({ settings: { soundEnabled: false, soundVolume: 0 } }),
}));

import { ThreadChip } from "@/components/board/board-cells";
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
    render(<ThreadChip item={row({ episode: THREAD, thread: "t3aa11bb", rounds: 3 })} onOpen={onOpen} />);
    await userEvent.click(screen.getByRole("button", { name: "Open thread" }));
    expect(onOpen).toHaveBeenCalledWith(THREAD);
  });

  it("is only an activity count, never the thread's id", () => {
    // The row opens the thread; the chip is a badge. So it shows how much has
    // been said — never the hex id, which is noise on every row.
    render(<ThreadChip item={row({ episode: THREAD, thread: "t3aa11bb", rounds: 3 })} onOpen={vi.fn()} />);
    const chip = screen.getByRole("button", { name: "Open thread" });
    expect(chip).toHaveTextContent("3");
    expect(chip).not.toHaveTextContent("t3aa11bb");
  });

  it("offers nothing on a row with no episode at all", () => {
    // A row created before threading has no episode yet; the chip is absent
    // until backfill binds one.
    const { container } = render(<ThreadChip item={row({ status: "open" })} onOpen={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("does not draw the room's own channel as a thread", () => {
    const live = "urn:ioc:mycelium:episode:atlas:live";
    const { container } = render(<ThreadChip item={row({ episode: live, rounds: 2 })} onOpen={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a count only where the thread has said something", () => {
    const { container, rerender } = render(<ThreadChip item={row({ episode: THREAD, rounds: 6 })} onOpen={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Open thread" })).toHaveTextContent("6");
    // A silent thread has no badge — "0 messages" reads as a claim about a
    // conversation nobody has had — but the row still opens on click.
    rerender(<ThreadChip item={row({ episode: THREAD, rounds: 0 })} onOpen={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("reads as a plain badge where nothing is listening", () => {
    render(<ThreadChip item={row({ episode: THREAD, rounds: 4 })} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
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
    // A row without an episode (not yet backfilled) refuses in the same terms
    // `board messages` refuses in, rather than falling back to the room,
    // which would show a different conversation than the one asked for.
    fetchMemories.mockResolvedValue([unbound]);
    const onOpenThread = vi.fn();
    renderWithSWR(<RoomBoard roomName="atlas" onOpenThread={onOpenThread} />);
    await screen.findByText("cache sweep");

    await userEvent.keyboard("j");
    await userEvent.keyboard("t");
    expect(onOpenThread).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/this memory carries no thread yet/),
    ).toBeInTheDocument();
  });

  it("opens the row's thread on `t` and on a click of the row itself", async () => {
    const onOpenThread = vi.fn();
    renderWithSWR(<RoomBoard roomName="atlas" onOpenThread={onOpenThread} />);
    const title = await screen.findByText("flip reads behind a flag");

    // Select the row the way the keyboard does, then reach its thread from the
    // caret — the board is keyboard-first and the thread is one of its verbs.
    await userEvent.keyboard("j");
    await userEvent.keyboard("t");
    await waitFor(() => expect(onOpenThread).toHaveBeenCalledWith(THREAD));

    // And by pointer: the row is the task, so a click on it opens the task.
    onOpenThread.mockClear();
    await userEvent.click(title);
    await waitFor(() => expect(onOpenThread).toHaveBeenCalledWith(THREAD));
  });
});
