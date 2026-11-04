// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** Switching rooms: a room opened again draws what it had at once, from the
 *  app's cache, and a long channel draws its newest rows first. */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SWRTestCache } from "@/test/swr";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";
import { layOut } from "@/test/scroll";

const fetchMessages = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchMessages: (...a: unknown[]) => fetchMessages(...a),
  fetchUsers: vi.fn().mockResolvedValue([]),
  fetchWireHistory: vi.fn().mockResolvedValue([]),
  fetchVerifierFlags: vi.fn().mockResolvedValue([]),
  fetchMemorySummaries: vi.fn().mockResolvedValue([]),
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

  it("reads back an older page only once every row it has is drawn", async () => {
    // A room with more behind its newest page, in a pane taller than its rows,
    // so the view reads as not full and asks for the page before.
    const messages = Array.from({ length: 40 }, (_, i) => said(i, i % 2 ? "alice" : "bob"));
    let drawnWhenAsked: boolean | null = null;
    fetchMessages.mockImplementation((_room: string, _limit: number, opts?: { before?: string | null }) => {
      if (opts?.before) {
        drawnWhenAsked ??= Boolean(screen.queryByText("line 0"));
        return new Promise(() => {});
      }
      return Promise.resolve({ messages, total: 400 });
    });
    render(
      <SWRTestCache>
        <EventStream roomName="sprint" />
      </SWRTestCache>,
    );
    const viewport = document.querySelector<HTMLElement>('[data-slot="scroll-area-viewport"]')!;
    layOut(viewport, "[data-event-id]", { rowHeight: 10, view: 2000 });
    await waitFor(() => expect(screen.getByText("line 0")).toBeTruthy(), { timeout: 5000 });
    await waitFor(() => expect(drawnWhenAsked).not.toBeNull(), { timeout: 5000 });
    expect(drawnWhenAsked).toBe(true);
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
    // The rest arrive a batch a frame; a loaded machine draws frames slowly.
    await waitFor(() => expect(screen.getByText("line 0")).toBeTruthy(), { timeout: 5000 });
  });
});
