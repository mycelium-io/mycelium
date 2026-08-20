// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";

vi.mock("@/lib/api", () => ({
  getSSEUrl: (room: string) => `/api/rooms/${room}/messages/stream`,
  fetchMessages: vi.fn().mockResolvedValue({
    messages: [
      {
        id: "1",
        message_type: "broadcast",
        sender_handle: "avery",
        content: "what should the cache TTL be?",
        created_at: "2026-08-17T09:00:00.000000+00:00",
        thread: "3f9a1c2d-aaaa",
      },
      {
        id: "2",
        message_type: "broadcast",
        sender_handle: "rowan",
        content: "60 seconds",
        created_at: "2026-08-17T09:00:00.000000+00:00",
        thread: "3f9a1c2d-aaaa",
      },
      {
        id: "3",
        message_type: "broadcast",
        sender_handle: "avery",
        content: "unrelated deploy question",
        created_at: "2026-08-17T09:00:00.000000+00:00",
        thread: null,
      },
    ],
  }),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchPendingInvites: vi.fn().mockResolvedValue([]),
  respondToInvite: vi.fn(),
  logFetchError: () => () => undefined,
}));

import { EventStream } from "@/components/event-stream";

describe("<EventStream /> threads", () => {
  beforeEach(() => {
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("follows one conversation and returns to the whole room", async () => {
    const user = userEvent.setup();
    render(<EventStream roomName="sprint" />);
    await act(async () => {});

    // The whole room by default: both conversations are in the feed.
    expect(await screen.findByText("what should the cache TTL be?")).toBeInTheDocument();
    expect(screen.getByText("unrelated deploy question")).toBeInTheDocument();

    // Following a thread hides everything that isn't part of it.
    await user.click(screen.getAllByTitle("Follow this thread")[0]);
    expect(screen.getByText("60 seconds")).toBeInTheDocument();
    expect(screen.queryByText("unrelated deploy question")).not.toBeInTheDocument();

    await user.click(screen.getByText("show whole room"));
    expect(screen.getByText("unrelated deploy question")).toBeInTheDocument();
  });
});
