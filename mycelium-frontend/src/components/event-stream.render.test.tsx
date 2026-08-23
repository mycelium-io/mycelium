// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithSWR } from "@/test/swr";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

vi.mock("@/lib/api", () => ({
  fetchMessages: vi.fn().mockResolvedValue({ messages: [] }),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchPendingInvites: vi.fn().mockResolvedValue([]),
  respondToInvite: vi.fn(),
  logFetchError: () => () => undefined,
}));

import { EventStream } from "@/components/event-stream";

const CREATED = "2026-08-04T10:00:00.000000+00:00";

/** The live SSE stream wraps a human/agent message as an L9 exchange envelope.
 *  An amendment is the same envelope with the `amend` subkind and the id of the
 *  message it revises in its causal parents. */
function l9Exchange(
  text: string,
  { id, sender = "user", amends }: { id?: string; sender?: string; amends?: string } = {},
) {
  return {
    id,
    message_type: "l9_exchange",
    sender_handle: sender,
    created_at: CREATED,
    content: JSON.stringify({
      content: text,
      l9: {
        header: {
          kind: "exchange",
          ...(amends ? { subkind: "amend" } : {}),
          message: { id, parents: amends ? [amends] : [] },
          participants: { actors: [{ id: sender, role: "human" }] },
        },
        payload: { type: "message", data: {} },
      },
    }),
  };
}

describe("<EventStream /> live message rendering", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("renders an l9_exchange streamed over SSE as a chat message", async () => {
    renderWithSWR(<EventStream roomName="sprint" />);
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

  it("folds a streamed amendment into the message it revises", async () => {
    renderWithSWR(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(l9Exchange("the TTL is 30s", { id: "m-1" }));
      es.emit(l9Exchange("the TTL is 300s", { id: "m-2", amends: "m-1" }));
    });

    // The open tab folds what a cold read would: one message, the newest text.
    expect(await screen.findByText("the TTL is 300s")).toBeInTheDocument();
    expect(screen.queryByText("the TTL is 30s")).not.toBeInTheDocument();
    expect(screen.getByText("(edited)")).toBeInTheDocument();
  });

  it("keeps an amendment from another sender as its own message", async () => {
    renderWithSWR(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(l9Exchange("mine", { id: "m-1" }));
      es.emit(l9Exchange("not what they said", { id: "m-2", sender: "ops", amends: "m-1" }));
    });

    // Folding it would put someone else's words under the original author's name.
    expect(await screen.findByText("mine")).toBeInTheDocument();
    expect(screen.getByText("not what they said")).toBeInTheDocument();
  });

  it("auto-scrolls the ScrollArea viewport, not the outer wrapper, on new messages", async () => {
    const scrollTo = vi.spyOn(Element.prototype, "scrollTo");
    renderWithSWR(<EventStream roomName="sprint" />);
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
    renderWithSWR(<EventStream roomName="sprint" />);
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
    renderWithSWR(<EventStream roomName="sprint" />);
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

  it("opens the episode a coordination notice names when its tag is clicked", async () => {
    const onOpenEpisode = vi.fn();
    renderWithSWR(<EventStream roomName="sprint" onOpenEpisode={onOpenEpisode} />);
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
              message: { episode: "urn:ioc:mycelium:episode:sprint:e4f1a2" },
            },
            payload: { type: "consensus", data: { assignments: { stack: "next" } } },
          },
        }),
      });
    });

    // The notice names the episode by its short id; the name is the way in.
    await userEvent.click(await screen.findByRole("button", { name: /Open episode e4f1a2/ }));
    expect(onOpenEpisode).toHaveBeenCalledWith("e4f1a2");
  });

  it("leaves the episode tag inert when nothing is listening for it", async () => {
    renderWithSWR(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit({
        message_type: "coordination_join",
        sender_handle: "alice",
        created_at: CREATED,
        content: JSON.stringify({
          handle: "alice",
          episode: "urn:ioc:mycelium:episode:sprint:e4f1a2",
        }),
      });
    });

    expect(await screen.findByText("e4f1a2")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open episode/ })).not.toBeInTheDocument();
  });

  it("warns loudly on an unhandled message_type instead of dropping it silently", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    renderWithSWR(<EventStream roomName="sprint" />);
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
