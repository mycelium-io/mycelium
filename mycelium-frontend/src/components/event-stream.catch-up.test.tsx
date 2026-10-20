// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The channel catching up on what it didn't get live.
 *
 * A channel stays open for hours and draws what arrives on the room's live
 * feed. When the feed comes back after a drop, when the window comes to the
 * front, or when something sent from it isn't echoed live, it reads what it
 * missed from the hub, and shows each message once however it arrived. A live
 * frame names the id the history read gives its message (`read_id`), so the
 * two copies are matched by id alone.
 */

import { act } from "react";
import { screen } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";
import { resetPending, sendPending } from "@/lib/pending-messages";

vi.mock("@/lib/api", () => ({
  fetchMessages: vi.fn(),
  sendRoomMessage: vi.fn(),
  fetchUsers: vi.fn().mockResolvedValue([]),
  fetchWireHistory: vi.fn().mockResolvedValue([]),
  fetchVerifierFlags: vi.fn().mockResolvedValue([]),
  fetchMemories: vi.fn().mockResolvedValue([]),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchRoomSettings: vi.fn().mockResolvedValue([]),
  logFetchError: () => () => undefined,
}));

const reported = vi.fn();
vi.mock("@/lib/report-to-app", () => ({ reportToApp: (line: string) => reported(line) }));

import { fetchMessages, sendRoomMessage } from "@/lib/api";
import { EventStream } from "@/components/event-stream";

const LIVE = "urn:ioc:mycelium:episode:sprint:live";

function at(minute: number): string {
  return new Date(Date.UTC(2026, 7, 20, 9, minute)).toISOString();
}

/** A message as the history read gives it. */
function stored(id: string, text: string, stamp: string, sender = "julia") {
  return { id, message_type: "broadcast", sender_handle: sender, content: text, created_at: stamp, episode: LIVE };
}

/** The same message as its live frame carries it: its own envelope id, and
 *  the history read's id as `read_id`. */
function live(readId: string, text: string, stamp: string, sender = "julia") {
  return {
    id: `frame-${readId}`,
    read_id: readId,
    message_type: "l9_exchange",
    sender_handle: sender,
    content: JSON.stringify({ content: text }),
    created_at: stamp.replace("Z", "+00:00"),
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

/** What a catch-up read finds: `messages` when asked `since`, else the room's
 *  first page, which holds one message. */
function hubHas(...messages: ReturnType<typeof stored>[]) {
  mockedMessages.mockImplementation(async (_room, _limit, query = {}) =>
    query.since
      ? { messages, total: messages.length }
      : { messages: [stored("row-1", "before the gap", at(1))], total: 1 },
  );
}

describe("<EventStream /> catching up", () => {
  beforeEach(() => {
    resetStreamHub();
    resetPending();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    mockedMessages.mockReset();
    reported.mockReset();
    hubHas();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows what was said while the room's feed was down, once it comes back", async () => {
    const es = await render();
    expect(screen.getByText("before the gap")).toBeInTheDocument();

    act(() => es.emitStatus("room", false, "sprint"));
    hubHas(stored("row-2", "during the gap", at(2)), stored("row-1", "before the gap", at(1)));
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
    hubHas(stored("row-2", "said once", at(2)));
    act(() => es.emitStatus("room", true, "sprint"));
    await settle();
    act(() => es.emit(live("row-2", "said once", at(2))));
    await settle();

    expect(screen.getAllByText("said once")).toHaveLength(1);
  });

  it("draws two messages that say the same thing at the same moment", async () => {
    const es = await render();
    act(() => es.emit(live("row-7", "on it", at(7), "builder")));
    act(() => es.emit(live("row-8", "on it", at(7), "builder")));
    await settle();

    expect(screen.getAllByText("on it")).toHaveLength(2);
  });

  it("checks when the window comes to the front, and subscribes again when the live feed lost a message", async () => {
    const es = await render();
    hubHas(stored("row-3", "never arrived live", at(3)));

    act(() => window.dispatchEvent(new Event("focus")));
    await settle();

    expect(screen.getByText("never arrived live")).toBeInTheDocument();
    expect(reported).toHaveBeenCalledWith(expect.stringContaining("missed 1 live message"));
    // And it still takes what arrives live after subscribing again.
    act(() => es.emit(live("row-4", "live again", at(4))));
    await settle();
    expect(screen.getByText("live again")).toBeInTheDocument();
  });

  it("catches up when something sent from here isn't echoed live", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await render();
    vi.mocked(sendRoomMessage).mockResolvedValue({ id: "row-9" } as never);
    const sentAt = new Date().toISOString();
    hubHas(stored("row-9", "did this land", sentAt, "julia"));

    await act(async () => {
      await sendPending("sprint", { sender: "julia", content: "did this land", episode: null });
    });
    const before = mockedMessages.mock.calls.filter((c) => c[2]?.since).length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(13_000);
    });
    await settle();

    expect(mockedMessages.mock.calls.filter((c) => c[2]?.since).length).toBeGreaterThan(before);
    expect(screen.getAllByText("did this land")).toHaveLength(1);
  });

  it("asks for nothing when the channel has nothing said to read from", async () => {
    mockedMessages.mockImplementation(async () => ({ messages: [], total: 0 }));
    await render();
    act(() => window.dispatchEvent(new Event("focus")));
    await settle();

    expect(mockedMessages.mock.calls.some((c) => c[2]?.since)).toBe(false);
  });
});
