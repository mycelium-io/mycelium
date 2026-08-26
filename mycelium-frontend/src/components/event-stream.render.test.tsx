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
  fetchL9History: vi.fn().mockResolvedValue([]),
  fetchMemories: vi.fn().mockResolvedValue([]),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
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

  it("lifts an l9_knowledge streamed over SSE into the rail, not the unhandled fallback", async () => {
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

    // A memory push is the room's state, not its speech: it reaches the rail
    // under the row's own name, once, and never the conversation.
    expect(await screen.findByText("Recently updated")).toBeInTheDocument();
    expect(screen.getAllByText("plan/tasks.md")).toHaveLength(1);
    expect(screen.getByText("@aligner")).toBeInTheDocument();
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("opens the episode's thread when a coordination notice's tag is clicked", async () => {
    const onOpenThread = vi.fn();
    renderWithSWR(<EventStream roomName="sprint" onOpenThread={onOpenThread} />);
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
    expect(onOpenThread).toHaveBeenCalledWith("urn:ioc:mycelium:episode:sprint:e4f1a2");
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

describe("<EventStream /> stick-to-bottom", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  const viewport = () =>
    document.querySelector('[data-slot="scroll-area-viewport"]') as HTMLElement;

  /** jsdom lays nothing out, so the viewport's scroll geometry is all zeros —
   *  which reads as "at the bottom". Give it a real scrollable shape. */
  function scrollTo(el: HTMLElement, top: number) {
    Object.defineProperty(el, "scrollHeight", { value: 1000, configurable: true });
    Object.defineProperty(el, "clientHeight", { value: 400, configurable: true });
    Object.defineProperty(el, "scrollTop", { value: top, writable: true, configurable: true });
    el.dispatchEvent(new Event("scroll"));
  }

  async function mountWithMessage(text: string) {
    renderWithSWR(<EventStream roomName="sprint" />);
    await act(async () => {});
    const es = FakeEventSource.latest();
    await act(async () => {
      es.open();
      es.emit(l9Exchange(text));
    });
    await screen.findByText(text);
    return es;
  }

  it("hides the jump button while the reader is on the tail", async () => {
    await mountWithMessage("first");
    expect(screen.queryByRole("button", { name: /Jump to latest/ })).not.toBeInTheDocument();
  });

  it("offers a jump button once the reader scrolls up off the tail", async () => {
    await mountWithMessage("first");

    await act(async () => { scrollTo(viewport(), 0); });

    expect(await screen.findByRole("button", { name: /Jump to latest/ })).toBeInTheDocument();
  });

  it("holds the reader's place instead of yanking them down to a new message", async () => {
    const es = await mountWithMessage("history the reader is reading");
    await act(async () => { scrollTo(viewport(), 0); });

    const scrollSpy = vi.spyOn(Element.prototype, "scrollTo");
    await act(async () => { es.emit(l9Exchange("landed while scrolled up")); });
    await screen.findByText("landed while scrolled up");

    expect(scrollSpy).not.toHaveBeenCalled();
    scrollSpy.mockRestore();
  });

  it("counts what landed while the reader was away", async () => {
    const es = await mountWithMessage("first");
    await act(async () => { scrollTo(viewport(), 0); });

    await act(async () => { es.emit(l9Exchange("second")); });
    expect(await screen.findByRole("button", { name: /1 new/ })).toHaveTextContent("1 new message");

    await act(async () => { es.emit(l9Exchange("third")); });
    expect(await screen.findByRole("button", { name: /2 new/ })).toHaveTextContent("2 new messages");
  });

  it("returns to the tail when the jump button is clicked", async () => {
    await mountWithMessage("first");
    await act(async () => { scrollTo(viewport(), 0); });
    const button = await screen.findByRole("button", { name: /Jump to latest/ });

    const scrollSpy = vi.spyOn(Element.prototype, "scrollTo");
    await userEvent.click(button);

    expect(scrollSpy).toHaveBeenCalledWith({ top: 1000, behavior: "smooth" });
    expect(screen.queryByRole("button", { name: /Jump to latest/ })).not.toBeInTheDocument();
    scrollSpy.mockRestore();
  });
});
