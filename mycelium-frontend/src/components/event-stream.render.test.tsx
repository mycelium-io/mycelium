// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { renderWithProviders } from "@/test/render-with-providers";

vi.mock("@/lib/api", () => ({
  getSSEUrl: (room: string) => `/api/rooms/${room}/messages/stream`,
  fetchMessages: vi.fn().mockResolvedValue({ messages: [] }),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchPendingInvites: vi.fn().mockResolvedValue([]),
  respondToInvite: vi.fn(),
  logFetchError: () => () => undefined,
}));

import { EventStream } from "@/components/event-stream";

const CREATED = "2026-08-04T10:00:00.000000+00:00";

/** The live SSE stream wraps a human/agent message as an L9 exchange envelope —
 *  the shape that was silently dropped before (issue #490). */
function l9Exchange(text: string) {
  return {
    message_type: "l9_exchange",
    sender_handle: "user",
    created_at: CREATED,
    content: JSON.stringify({
      content: text,
      l9: {
        header: { kind: "exchange", participants: { actors: [{ id: "user", role: "human" }] } },
        payload: { type: "message", data: {} },
      },
    }),
  };
}

describe("<EventStream /> live message rendering", () => {
  beforeEach(() => {
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("renders an l9_exchange streamed over SSE as a chat message", async () => {
    renderWithProviders(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(l9Exchange("hello over the live channel"));
    });

    // The prose is unwrapped from the L9 envelope and rendered like a broadcast,
    // so the live feed matches what a refresh (REST) would show.
    expect(await screen.findByText("hello over the live channel")).toBeInTheDocument();
  });

  it("warns loudly on an unhandled message_type instead of dropping it silently", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    renderWithProviders(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit({
        message_type: "brand_new_type",
        sender_handle: "x",
        created_at: CREATED,
        content: "{}",
      });
    });

    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining('unhandled message_type "brand_new_type"'),
      expect.anything(),
    );
    warn.mockRestore();
  });
});
