// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Reading back through the channel (issue #899).
 *
 * The feed used to be one fetch of the newest messages and nothing else: no
 * scroll-back, no load-older, and a default of fifty against a rail that loaded
 * two hundred. So a room with hundreds of messages in it read as having only
 * the last few minutes of churn. These cover the walk back — that a page before
 * is asked for, that it is asked for by content rather than position, that it
 * stops at the start of the room, and that it does not double what is already
 * on screen.
 *
 * jsdom does no layout, so the viewport never overflows: the fill pass (the one
 * that keeps pulling until there is something to scroll) is what drives paging
 * here, which is the same code path a scroll to the top takes.
 */

import { act } from "react";
import { screen } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

vi.mock("@/lib/api", () => ({
  fetchMessages: vi.fn(),
  fetchL9History: vi.fn().mockResolvedValue([]),
  fetchMemories: vi.fn().mockResolvedValue([]),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  logFetchError: () => () => undefined,
}));

import { fetchL9History, fetchMessages } from "@/lib/api";
import { EventStream } from "@/components/event-stream";

/** A minute apart, so a page's oldest message is an unambiguous cursor. */
function said(index: number) {
  return {
    id: `m-${index}`,
    message_type: "broadcast",
    sender_handle: "julia",
    content: `msg ${index}`,
    created_at: new Date(Date.UTC(2026, 7, 20, 9, index)).toISOString(),
  };
}

/** The room's messages newest-first, as the backend serves them. */
function page(indices: number[], total: number) {
  return { messages: indices.map(said).reverse(), total };
}

const mockedMessages = vi.mocked(fetchMessages);
const mockedL9 = vi.mocked(fetchL9History);

/** The `before` cursor each `fetchMessages` call was made with. */
function cursors() {
  return mockedMessages.mock.calls.map((call) => call[2]?.before ?? null);
}

async function render() {
  renderWithSWR(<EventStream roomName="sprint" />);
  await act(async () => {});
  await act(async () => {});
  await act(async () => {});
}

describe("<EventStream /> reading back", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    mockedMessages.mockReset();
    mockedL9.mockReset().mockResolvedValue([]);
  });

  it("asks for the page before, keyed off the oldest message loaded", async () => {
    mockedMessages
      .mockResolvedValueOnce(page([3, 4, 5], 6))
      .mockResolvedValue(page([0, 1, 2], 3));

    await render();

    // Not an offset: the second read names the stamp of the oldest message it
    // already holds, so a message arriving live cannot shift the page under it.
    expect(cursors()[0]).toBeFalsy();
    expect(cursors()[1]).toBe(said(3).created_at);
    expect(await screen.findByText("msg 0")).toBeInTheDocument();
    expect(await screen.findByText("msg 5")).toBeInTheDocument();
  });

  it("reads both halves of the feed at the same depth", async () => {
    mockedMessages.mockResolvedValue(page([0, 1, 2], 3));

    await render();

    // The rail used to load two hundred frames of churn while the conversation
    // loaded the backend's default fifty, so the prose was the shallower half
    // of a feed assembled from both.
    expect(mockedMessages.mock.calls[0][1]).toBe(mockedL9.mock.calls[0][1]);
  });

  it("stops once the room has no page before", async () => {
    mockedMessages
      .mockResolvedValueOnce(page([3, 4, 5], 6))
      .mockResolvedValue(page([0, 1, 2], 3));

    await render();
    const settled = mockedMessages.mock.calls.length;
    await act(async () => {});
    await act(async () => {});

    // The second page returned everything left (total === length), so there is
    // nothing before it and nothing more to ask.
    expect(mockedMessages.mock.calls.length).toBe(settled);
    expect(await screen.findByText("Beginning of the room")).toBeInTheDocument();
  });

  it("does not count an older page as messages that landed while you were away", async () => {
    // The jump-back pill used to hold `visible.length` at the moment the reader
    // left the tail and subtract it. Every message in a page fetched by reading
    // back lands *above* that mark, so walking through a room's history read as
    // hundreds of new messages arriving in it.
    mockedMessages
      .mockResolvedValueOnce(page([3, 4, 5], 6))
      .mockResolvedValue(page([0, 1, 2], 3));

    // A viewport with something to scroll, so the fill pass holds off and the
    // page before is fetched by the reader reaching the top — off the tail,
    // which is the state the count is about.
    const geometry = { value: 0, configurable: true };
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", { ...geometry, value: 1000 });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { ...geometry, value: 400 });

    renderWithSWR(<EventStream roomName="sprint" />);
    await act(async () => {});
    await act(async () => {});
    expect(mockedMessages).toHaveBeenCalledTimes(1);

    // Up to the top, which is the reader asking for what came before.
    const viewport = document.querySelector("[data-slot='scroll-area-viewport']") as HTMLElement;
    await act(async () => {
      viewport.scrollTop = 0;
      viewport.dispatchEvent(new Event("scroll"));
    });
    await act(async () => {});
    await act(async () => {});

    expect(await screen.findByText("msg 0")).toBeInTheDocument();
    // Off the tail, so the jump-back control is there — but with nothing to
    // count, because everything that landed came from before the mark.
    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /\d+ new/ })).not.toBeInTheDocument();

    Reflect.deleteProperty(HTMLElement.prototype, "scrollHeight");
    Reflect.deleteProperty(HTMLElement.prototype, "clientHeight");
  });

  it("shows a message once when an older page overlaps what is on screen", async () => {
    // The live stream never stops while a reader walks back, so a page can
    // repeat rows already loaded. Dedup is by the backend's id.
    mockedMessages
      .mockResolvedValueOnce(page([3, 4, 5], 6))
      .mockResolvedValue(page([2, 3, 4], 3));

    await render();

    expect(await screen.findAllByText("msg 3")).toHaveLength(1);
    expect(await screen.findAllByText("msg 4")).toHaveLength(1);
  });
});
