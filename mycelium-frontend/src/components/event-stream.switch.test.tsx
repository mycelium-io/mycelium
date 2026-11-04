// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** Switching rooms: a room opened again draws what it had at once, from the
 *  app's cache, and a long channel draws its newest rows first. */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SWRTestCache } from "@/test/swr";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

const fetchMessages = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchMessages: (...a: unknown[]) => fetchMessages(...a),
  fetchUsers: vi.fn().mockResolvedValue([]),
  fetchWireHistory: vi.fn().mockResolvedValue([]),
  fetchVerifierFlags: vi.fn().mockResolvedValue([]),
  fetchMemories: vi.fn().mockResolvedValue([]),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchRoomSettings: vi.fn().mockResolvedValue([]),
  logFetchError: () => () => undefined,
}));

import { EventStream } from "@/components/event-stream";

function said(i: number, sender = "alice") {
  const at = new Date(Date.UTC(2026, 7, 4, 10, i)).toISOString();
  return { id: `m${i}`, message_type: "broadcast", sender_handle: sender, created_at: at, content: `line ${i}` };
}

describe("<EventStream /> across room switches", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    fetchMessages.mockReset();
  });

  it("draws a room it showed before at once, while its fresh read is still out", async () => {
    fetchMessages.mockResolvedValueOnce({ messages: [said(1)], total: 1 });
    // The channel is drawn anew for each room it opens, like the room's dock does.
    const view = (key: string) => (
      <SWRTestCache>
        <EventStream key={key} roomName="sprint" />
      </SWRTestCache>
    );
    const { rerender } = render(view("first"));
    expect(await screen.findByText("line 1")).toBeTruthy();

    fetchMessages.mockReturnValue(new Promise(() => {}));
    rerender(view("again"));
    // On screen before the hub answers the second read, which never does here.
    expect(screen.getByText("line 1")).toBeTruthy();
  });

  it("draws every row of a long channel, newest first", async () => {
    const messages = Array.from({ length: 40 }, (_, i) => said(i, i % 2 ? "alice" : "bob"));
    fetchMessages.mockResolvedValue({ messages, total: 40 });
    render(
      <SWRTestCache>
        <EventStream roomName="sprint" />
      </SWRTestCache>,
    );
    expect(await screen.findByText("line 39")).toBeTruthy();
    await waitFor(() => expect(screen.getByText("line 0")).toBeTruthy());
  });
});
