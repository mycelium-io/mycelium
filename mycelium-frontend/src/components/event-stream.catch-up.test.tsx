// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The channel catching up on what it didn't get live.
 *
 * A channel stays open for hours and draws what arrives on the room's live
 * feed. When the feed drops and comes back, or the channel's own subscription
 * stops receiving while the room keeps talking, it reads what it missed from
 * the hub, and shows each message once however it arrived.
 */

import { act } from "react";
import { screen } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

vi.mock("@/lib/api", () => ({
  fetchMessages: vi.fn(),
  fetchUsers: vi.fn().mockResolvedValue([]),
  fetchWireHistory: vi.fn().mockResolvedValue([]),
  fetchVerifierFlags: vi.fn().mockResolvedValue([]),
  fetchMemories: vi.fn().mockResolvedValue([]),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchRoomSettings: vi.fn().mockResolvedValue([]),
  logFetchError: () => () => undefined,
}));

import { fetchMessages } from "@/lib/api";
import { EventStream } from "@/components/event-stream";

const LIVE = "urn:ioc:mycelium:episode:sprint:live";

function at(minute: number): string {
  return new Date(Date.UTC(2026, 7, 20, 9, minute)).toISOString();
}

/** A message as the hub stores it. */
function stored(id: string, text: string, minute: number, sender = "julia") {
  return { id, message_type: "broadcast", sender_handle: sender, content: text, created_at: at(minute), episode: LIVE };
}

/** The same message as its live frame carries it: another id, the same
 *  sender, stamp and text. */
function live(id: string, text: string, minute: number, sender = "julia") {
  return {
    id,
    message_type: "l9_exchange",
    sender_handle: sender,
    content: JSON.stringify({ content: text }),
    created_at: at(minute).replace("Z", "+00:00"),
    episode: LIVE,
  };
}

const mockedMessages = vi.mocked(fetchMessages);

async function settle() {
  await act(async () => {});
  await act(async () => {});
  await act(async () => {});
}

async function render() {
  renderWithSWR(<EventStream roomName="sprint" />);
  await settle();
  const es = FakeEventSource.latest();
  act(() => es.goLive());
  await settle();
  return es;
}

describe("<EventStream /> catching up", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    mockedMessages.mockReset();
    mockedMessages.mockImplementation(async (_room, _limit, query = {}) =>
      query.since ? { messages: [], total: 0 } : { messages: [stored("row-1", "before the gap", 1)], total: 1 },
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows what was said while the room's feed was down, once it comes back", async () => {
    const es = await render();
    expect(screen.getByText("before the gap")).toBeInTheDocument();

    act(() => es.emitStatus("room", false, "sprint"));
    mockedMessages.mockImplementation(async (_room, _limit, query = {}) => ({
      messages: query.since ? [stored("row-2", "during the gap", 2), stored("row-1", "before the gap", 1)] : [],
      total: 2,
    }));
    act(() => es.emitStatus("room", true, "sprint"));
    await settle();

    expect(screen.getByText("during the gap")).toBeInTheDocument();
    expect(screen.getAllByText("before the gap")).toHaveLength(1);
    // Read from the newest message it had, not the whole room again.
    const since = mockedMessages.mock.calls.map((c) => c[2]?.since).filter(Boolean);
    expect(since.at(-1)).toBe(at(1));
  });

  it("draws a message once when its live frame lands after a catch-up read it", async () => {
    const es = await render();
    act(() => es.emitStatus("room", false, "sprint"));
    mockedMessages.mockImplementation(async (_room, _limit, query = {}) => ({
      messages: query.since ? [stored("row-2", "said once", 2)] : [],
      total: 1,
    }));
    act(() => es.emitStatus("room", true, "sprint"));
    await settle();
    act(() => es.emit(live("frame-2", "said once", 2)));
    await settle();

    expect(screen.getAllByText("said once")).toHaveLength(1);
  });

  it("checks when the window comes to the front, and subscribes again when the live feed lost a message", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const es = await render();
    mockedMessages.mockImplementation(async (_room, _limit, query = {}) => ({
      messages: query.since ? [stored("row-3", "never arrived live", 3)] : [],
      total: 1,
    }));

    act(() => window.dispatchEvent(new Event("focus")));
    await settle();

    expect(screen.getByText("never arrived live")).toBeInTheDocument();
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("missed 1 live message"));
    // And it still takes what arrives live after subscribing again.
    act(() => es.emit(live("frame-4", "live again", 4)));
    await settle();
    expect(screen.getByText("live again")).toBeInTheDocument();
  });

  it("asks for nothing when the channel has nothing said to read from", async () => {
    mockedMessages.mockImplementation(async () => ({ messages: [], total: 0 }));
    await render();
    act(() => window.dispatchEvent(new Event("focus")));
    await settle();

    expect(mockedMessages.mock.calls.some((c) => c[2]?.since)).toBe(false);
  });
});
