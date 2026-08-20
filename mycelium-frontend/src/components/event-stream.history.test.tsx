// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Reverse-scrolling a room's history (issue #654).
 *
 * The feed used to show one fixed window of the newest messages and stop there,
 * leaving everything older unreachable in the browser. It now walks back a page
 * at a time as the reader nears the top — without yanking them to the bottom or
 * showing a message twice.
 */

import { act } from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { FakeIntersectionObserver } from "@/test/fake-intersection-observer";

const fetchMessages = vi.fn();

vi.mock("@/lib/api", () => ({
  getSSEUrl: (room: string) => `/api/rooms/${room}/messages/stream`,
  fetchMessages: (...args: unknown[]) => fetchMessages(...args),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchPendingInvites: vi.fn().mockResolvedValue([]),
  respondToInvite: vi.fn(),
  logFetchError: () => () => undefined,
}));

import { EventStream } from "@/components/event-stream";

const CREATED = "2026-08-04T10:00:00.000000+00:00";

/** A page of chat, newest first — the order the hub serves. */
function page(ids: string[], nextCursor: string | null) {
  return {
    messages: ids.map((id) => ({
      id,
      message_type: "broadcast",
      sender_handle: "operator",
      content: `message ${id}`,
      created_at: CREATED,
    })),
    total: 6,
    next_cursor: nextCursor,
    has_more: nextCursor !== null,
  };
}

/** Render the feed with its first page loaded and the SSE stream open. */
async function openRoom() {
  render(<EventStream roomName="sprint" />);
  await act(async () => {});
  await act(async () => {
    FakeEventSource.latest().open();
  });
}

/** Scroll to the top and let the page that lands settle. */
async function scrollToTop() {
  await act(async () => {
    FakeIntersectionObserver.latest().trigger();
  });
  await act(async () => {});
}

describe("<EventStream /> history pagination", () => {
  beforeEach(() => {
    FakeEventSource.reset();
    FakeIntersectionObserver.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
    fetchMessages.mockReset();
  });

  it("opens on the newest page and asks for it by page, not for everything", async () => {
    fetchMessages.mockResolvedValue(page(["m6", "m5"], "cursor-1"));

    await openRoom();

    expect(await screen.findByText("message m5")).toBeInTheDocument();
    expect(fetchMessages).toHaveBeenCalledWith("sprint", 50, null);
  });

  it("loads the page before it when the reader reaches the top", async () => {
    fetchMessages
      .mockResolvedValueOnce(page(["m6", "m5"], "cursor-1"))
      .mockResolvedValueOnce(page(["m4", "m3"], null));

    await openRoom();
    await screen.findByText("message m5");
    await scrollToTop();

    // The older page arrived, and it arrived *above* what was already there.
    expect(await screen.findByText("message m3")).toBeInTheDocument();
    expect(fetchMessages).toHaveBeenLastCalledWith("sprint", 50, "cursor-1");
    const rendered = screen.getAllByText(/^message m\d$/).map((el) => el.textContent);
    expect(rendered).toEqual(["message m3", "message m4", "message m5", "message m6"]);
  });

  it("stops asking once history runs out", async () => {
    fetchMessages.mockResolvedValue(page(["m2", "m1"], null));

    await openRoom();
    await screen.findByText("message m1");

    // A first page that ends history leaves nothing to observe for.
    expect(FakeIntersectionObserver.instances).toHaveLength(0);
    expect(fetchMessages).toHaveBeenCalledTimes(1);
  });

  it("shows a message once when the live stream already delivered it", async () => {
    fetchMessages
      .mockResolvedValueOnce(page(["m6"], "cursor-1"))
      .mockResolvedValueOnce(page(["m6", "m5"], null));

    await openRoom();
    await screen.findByText("message m6");
    await scrollToTop();

    await screen.findByText("message m5");
    expect(screen.getAllByText("message m6")).toHaveLength(1);
  });

  it("does not yank a reader who has scrolled up down to the newest message", async () => {
    fetchMessages
      .mockResolvedValueOnce(page(["m6", "m5"], "cursor-1"))
      .mockResolvedValueOnce(page(["m4", "m3"], null));

    await openRoom();
    await screen.findByText("message m5");

    const viewport = document.querySelector("[data-slot=scroll-area-viewport]");
    if (!viewport) throw new Error("no scroll viewport rendered");
    Object.defineProperty(viewport, "scrollHeight", { value: 1000, configurable: true });
    Object.defineProperty(viewport, "clientHeight", { value: 200, configurable: true });
    Object.defineProperty(viewport, "scrollTop", { value: 0, writable: true, configurable: true });
    await act(async () => {
      viewport.dispatchEvent(new Event("scroll"));
    });

    const scrollTo = vi.spyOn(Element.prototype, "scrollTo");
    await scrollToTop();
    await screen.findByText("message m3");

    expect(scrollTo).not.toHaveBeenCalled();
  });
});

describe("<EventStream /> history pagination across rooms", () => {
  beforeEach(() => {
    FakeEventSource.reset();
    FakeIntersectionObserver.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
    fetchMessages.mockReset();
  });

  it("does not spill a page in flight into the room the reader switched to", async () => {
    // A page requested for one room lands after the reader has moved to another.
    // It belongs to a history nobody is looking at any more.
    let releaseSprint: (value: unknown) => void = () => {};
    fetchMessages
      .mockImplementationOnce(
        () => new Promise((resolve) => { releaseSprint = resolve; }),
      )
      .mockResolvedValueOnce(page(["m1"], null));

    const view = render(<EventStream roomName="sprint" />);
    await act(async () => {});
    view.rerender(<EventStream roomName="retro" />);
    await act(async () => {});
    await screen.findByText("message m1");

    await act(async () => {
      releaseSprint(page(["stale"], "cursor-1"));
    });

    expect(screen.queryByText("message stale")).not.toBeInTheDocument();
    expect(screen.getByText("message m1")).toBeInTheDocument();
  });
});

describe("<EventStream /> history pagination, when a page holds no chat", () => {
  beforeEach(() => {
    FakeEventSource.reset();
    FakeIntersectionObserver.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
    fetchMessages.mockReset();
  });

  it("keeps walking rather than declaring the room empty", async () => {
    // The newest page is all non-chat rows the channel view filters out. That is
    // a window with nothing to show, not a room with nothing in it.
    fetchMessages
      .mockResolvedValueOnce({
        messages: [
          { id: "t1", message_type: "coordination_tick", sender_handle: "aligner", content: "{}" },
        ],
        total: 2,
        next_cursor: "cursor-1",
        has_more: true,
      })
      .mockResolvedValueOnce(page(["m1"], null));

    await openRoom();
    expect(screen.queryByText("No messages yet")).not.toBeInTheDocument();

    await scrollToTop();

    expect(await screen.findByText("message m1")).toBeInTheDocument();
  });
});
