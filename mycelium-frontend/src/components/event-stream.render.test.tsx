// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";

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
    render(<EventStream roomName="sprint" />);
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

  it("auto-scrolls the ScrollArea viewport, not the outer wrapper, on new messages", async () => {
    const scrollTo = vi.spyOn(Element.prototype, "scrollTo");
    render(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(l9Exchange("stick to bottom"));
    });
    await screen.findByText("stick to bottom");

    expect(scrollTo).toHaveBeenCalled();
    const scrolledEl = scrollTo.mock.contexts[scrollTo.mock.contexts.length - 1] as Element;
    expect(scrolledEl.getAttribute("data-slot")).toBe("scroll-area-viewport");
    scrollTo.mockRestore();
  });

  it("renders an l9_commit streamed over SSE as a consensus notice, not the unhandled fallback", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit({
        message_type: "l9_commit",
        sender_handle: "aligner",
        created_at: CREATED,
        content: JSON.stringify({
          content: "consensus reached",
          l9: {
            header: {
              kind: "commit",
              subkind: "converged",
              message: { episode: "urn:ioc:mycelium:episode:sprint:s1" },
            },
            payload: { type: "consensus", data: { assignments: { stack: "next" }, metrics: { gar: 0.8 } } },
          },
        }),
      });
    });

    expect(await screen.findByText("Consensus")).toBeInTheDocument();
    expect(screen.getByText("· 1 issue agreed", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("GAR 0.80", { exact: false })).toBeInTheDocument();
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("renders an l9_knowledge streamed over SSE as a knowledge notice, not the unhandled fallback", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit({
        message_type: "l9_knowledge",
        sender_handle: "system",
        created_at: CREATED,
        content: JSON.stringify({
          content: "plan updated → plan/tasks.md",
          l9: {
            header: { kind: "knowledge", subkind: "distillation" },
            payload: { type: "distillation", data: { key: "plan/tasks.md", updated_by: "aligner" } },
          },
        }),
      });
    });

    expect(await screen.findByText("plan updated → plan/tasks.md")).toBeInTheDocument();
    expect(screen.getByText("Knowledge")).toBeInTheDocument();
    expect(screen.getByText("by @aligner", { exact: false })).toBeInTheDocument();
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("warns loudly on an unhandled message_type instead of dropping it silently", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(<EventStream roomName="sprint" />);
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
