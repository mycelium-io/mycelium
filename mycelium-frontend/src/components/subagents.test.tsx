// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";
import type { Subagent } from "@/lib/api";

const review: Subagent = {
  handle: "builder:review",
  parent: "builder",
  name: "review",
  state: "working",
  started_at: "2026-08-04T09:58:00+00:00",
  ended_at: null,
};

vi.mock("@/lib/api", () => ({
  fetchMessages: vi.fn().mockResolvedValue({ messages: [] }),
  fetchUsers: vi.fn().mockResolvedValue([]),
  fetchWireHistory: vi.fn().mockResolvedValue([]),
  fetchVerifierFlags: vi.fn().mockResolvedValue([]),
  fetchMemorySummaries: vi.fn().mockResolvedValue([]),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchRoomSettings: vi.fn().mockResolvedValue([]),
  // An ended subagent is still known, so what it said keeps its name.
  fetchSubagents: vi.fn().mockResolvedValue([
    {
      handle: "builder:review",
      parent: "builder",
      name: "review",
      state: "ended",
      started_at: "2026-08-04T09:58:00+00:00",
      ended_at: "2026-08-04T10:01:00+00:00",
    },
  ]),
  logFetchError: () => () => undefined,
}));

import { SubagentRow } from "@/components/agents-panel";
import { EventStream } from "@/components/event-stream";

describe("a subagent's row in Members", () => {
  it("shows its own name, and that it's working", () => {
    render(<SubagentRow subagent={review} />);
    expect(screen.getByText("review")).toBeInTheDocument();
    expect(screen.getByText("working")).toBeInTheDocument();
    expect(screen.getByTitle("@builder:review")).not.toHaveClass("opacity-50");
  });

  it("fades once it's done", () => {
    render(<SubagentRow subagent={{ ...review, state: "done" }} />);
    expect(screen.getByText("done")).toBeInTheDocument();
    expect(screen.getByTitle("@builder:review")).toHaveClass("opacity-50");
  });
});

describe("a subagent's message in the chat", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("reads as its name, its handle and a subagent tag, after it has ended", async () => {
    renderWithSWR(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();
    await act(async () => {
      es.open();
      es.emit({
        id: "m-sub",
        message_type: "broadcast",
        sender_handle: "builder:review",
        created_at: "2026-08-04T10:00:00.000000+00:00",
        content: "the retry path looks right",
      });
    });

    await screen.findByText("the retry path looks right");
    expect(await screen.findByText("@builder:review")).toBeInTheDocument();
    expect(screen.getByText("review")).toBeInTheDocument();
    expect(screen.getByText("subagent")).toBeInTheDocument();
  });
});
