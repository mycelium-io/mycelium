// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";

vi.mock("@/lib/api", () => ({
  getSSEUrl: (room: string) => `/api/rooms/${room}/messages/stream`,
  fetchMessages: vi.fn().mockResolvedValue({ messages: [] }),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchPendingInvites: vi.fn().mockResolvedValue([]),
  respondToInvite: vi.fn().mockResolvedValue({ id: "i1", status: "accepted" }),
  logFetchError: () => () => undefined,
}));

import { EventStream } from "@/components/event-stream";
import { respondToInvite } from "@/lib/api";

const CREATED = "2026-08-04T10:00:00.000000+00:00";

function consentRequest() {
  return {
    message_type: "consent_request",
    sender_handle: "system",
    created_at: CREATED,
    content: JSON.stringify({
      id: "i1",
      room: "sprint",
      agent: "bob",
      requested_by: "alice",
      trigger_text: "need bob on this",
      status: "pending",
      created_at: CREATED,
    }),
  };
}

describe("<EventStream /> consent prompt", () => {
  beforeEach(() => {
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.mocked(respondToInvite).mockClear();
  });

  it("surfaces a consent_request bus event as an accept/decline prompt", async () => {
    render(<EventStream roomName="sprint" />);
    // Let the initial fetchPendingInvites effect settle so its empty result
    // can't overwrite the invite the bus event adds below.
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(consentRequest());
    });

    expect(await screen.findByText("Incoming agent request")).toBeInTheDocument();
    expect(screen.getByText("Accept")).toBeInTheDocument();
    expect(screen.getByText("Decline")).toBeInTheDocument();
  });

  it("accept wiring calls the invites endpoint with the accept decision", async () => {
    render(<EventStream roomName="sprint" />);
    // Let the initial fetchPendingInvites effect settle so its empty result
    // can't overwrite the invite the bus event adds below.
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(consentRequest());
    });

    fireEvent.click(await screen.findByText("Accept"));
    expect(respondToInvite).toHaveBeenCalledWith("sprint", "i1", "accept");
  });

  it("decline wiring calls the invites endpoint with the decline decision", async () => {
    render(<EventStream roomName="sprint" />);
    // Let the initial fetchPendingInvites effect settle so its empty result
    // can't overwrite the invite the bus event adds below.
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(consentRequest());
    });

    fireEvent.click(await screen.findByText("Decline"));
    expect(respondToInvite).toHaveBeenCalledWith("sprint", "i1", "decline");
  });
});
