// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RoomA2aView } from "@/components/room-a2a";
import type { A2aBridgeState } from "@/lib/api";

vi.mock("@/lib/room-data", () => ({
  useA2aBridge: vi.fn(),
}));

import { useA2aBridge } from "@/lib/room-data";

function bridge(over: Partial<A2aBridgeState> = {}): A2aBridgeState {
  return {
    room: "pricing-model",
    agents: [
      {
        handle: "market-data",
        description: "External competitor pricing feed.",
        card: "https://market-data.example",
        endpoint: "https://market-data.example/a2a",
        skills: ["quote", "benchmark"],
        calls_ok: 2,
        calls_failed: 1,
        last_call_at: "2026-08-12T17:20:00Z",
        proxied: true,
      },
    ],
    exchanges: [
      {
        id: "a2a-1",
        handle: "market-data",
        direction: "outbound",
        status: "ok",
        at: "2026-08-12T17:20:00Z",
        endpoint: "https://market-data.example/a2a",
        peer: "finance",
        prompt: "@finance: what are comparable Pro tiers charging?",
        reply: "Median $39/seat.",
        detail: null,
        duration_ms: 812,
      },
      {
        id: "a2a-2",
        handle: "market-data",
        direction: "outbound",
        status: "error",
        at: "2026-08-12T17:22:00Z",
        endpoint: "https://market-data.example/a2a",
        peer: "growth",
        prompt: "@growth: churn at $29?",
        reply: "",
        detail: "send failed: timeout after 120s",
        duration_ms: 120004,
      },
    ],
    outbound_ok: 2,
    outbound_failed: 1,
    exposure: {
      card_url: "http://hub/api/rooms/pricing-model/.well-known/agent-card.json",
      rpc_url: "http://hub/api/rooms/pricing-model/a2a",
      skills: ["summarize"],
      card_fetches: 4,
      messages: 1,
      last_card_fetch_at: "2026-08-12T17:21:00Z",
      last_message_at: "2026-08-12T17:21:00Z",
    },
    ...over,
  };
}

function mockBridge(state: A2aBridgeState | null) {
  vi.mocked(useA2aBridge).mockReturnValue({ bridge: state, loading: false, refresh: vi.fn() });
}

describe("RoomA2aView", () => {
  beforeEach(() => {
    vi.mocked(useA2aBridge).mockReset();
  });

  it("summarizes the bridge and flags it as proxied", () => {
    mockBridge(bridge());
    render(<RoomA2aView roomName="pricing-model" />);

    expect(screen.getByText("A2A bridge")).toBeInTheDocument();
    // The honest boundary cue is visible without expanding.
    expect(screen.getByText(/not in the MLS group/)).toBeInTheDocument();
  });

  it("lists bridged agents with their endpoint and skills once expanded", async () => {
    mockBridge(bridge());
    render(<RoomA2aView roomName="pricing-model" />);

    await userEvent.click(screen.getByRole("button", { expanded: false }));

    expect(screen.getAllByText("@market-data").length).toBeGreaterThan(0);
    expect(screen.getByText("https://market-data.example/a2a")).toBeInTheDocument();
    expect(screen.getByText("quote")).toBeInTheDocument();
    expect(screen.getByText("benchmark")).toBeInTheDocument();
  });

  it("shows the room's own card as the inbound half", async () => {
    mockBridge(bridge());
    render(<RoomA2aView roomName="pricing-model" />);

    await userEvent.click(screen.getByRole("button", { expanded: false }));

    expect(
      screen.getByText("http://hub/api/rooms/pricing-model/.well-known/agent-card.json"),
    ).toBeInTheDocument();
  });

  it("renders a failed call with its reason, not as silence", async () => {
    mockBridge(bridge());
    render(<RoomA2aView roomName="pricing-model" />);

    await userEvent.click(screen.getByRole("button", { expanded: false }));

    expect(screen.getByText("send failed: timeout after 120s")).toBeInTheDocument();
    expect(screen.getByText("Median $39/seat.")).toBeInTheDocument();
  });

  it("renders nothing for a room with no bridge and no traffic", () => {
    mockBridge(
      bridge({
        agents: [],
        exchanges: [],
        outbound_ok: 0,
        outbound_failed: 0,
        exposure: {
          ...bridge().exposure,
          card_fetches: 0,
          messages: 0,
          last_card_fetch_at: null,
          last_message_at: null,
        },
      }),
    );
    const { container } = render(<RoomA2aView roomName="scratch" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the hub can't serve the bridge state", () => {
    mockBridge(null);
    const { container } = render(<RoomA2aView roomName="pricing-model" />);

    expect(container).toBeEmptyDOMElement();
  });
});
