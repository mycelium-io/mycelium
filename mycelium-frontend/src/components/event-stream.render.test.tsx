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
  fetchPlan: vi.fn().mockResolvedValue({ documents: [] }),
  respondToInvite: vi.fn(),
  logFetchError: () => () => undefined,
}));

import { EventStream } from "@/components/event-stream";

const CREATED = "2026-08-04T10:00:00.000000+00:00";

/** The live SSE stream wraps a human/agent message as an L9 exchange envelope. */
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

  it("does not strand the reader after they page through the plan view", async () => {
    // Plan and channel share one scroll viewport, so a plan document's scroll
    // position must not be read as the reader leaving the channel's tail.
    const { rerender } = renderWithSWR(<EventStream roomName="sprint" view="plan" />);
    await act(async () => {});
    const es = FakeEventSource.latest();
    await act(async () => {
      es.open();
      es.emit(l9Exchange("posted while the plan was open"));
    });

    await act(async () => { scrollTo(viewport(), 0); });
    rerender(<EventStream roomName="sprint" view="channel" />);
    await act(async () => {});

    expect(screen.queryByRole("button", { name: /Jump to latest/ })).not.toBeInTheDocument();
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
