// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// What the room hears while its threads are busy.
//
// The whole claim of the task model is that a task absorbs its own
// argument and the channel stays readable — so these cases are about what does
// *not* appear as much as what does.

import { act } from "react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithSWR } from "@/test/swr";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";
import { fetchL9History, fetchMessages, fetchMemories } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchMessages: vi.fn().mockResolvedValue({ messages: [] }),
  fetchL9History: vi.fn().mockResolvedValue([]),
  fetchMemories: vi.fn().mockResolvedValue([]),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchPendingInvites: vi.fn().mockResolvedValue([]),
  respondToInvite: vi.fn(),
  logFetchError: () => () => undefined,
}));

import { EventStream } from "@/components/event-stream";

const ROOM = "atlas";
const LIVE = "urn:ioc:mycelium:episode:atlas:live";
const THREAD = "urn:ioc:mycelium:episode:atlas:t3aa11bb";
const CREATED = "2026-08-04T10:00:00.000000+00:00";

/** A message as the live stream carries it: prose inside an L9 exchange. */
function said(text: string, episode: string | null, sender = "growth") {
  return {
    id: `m-${text.length}-${sender}`,
    message_type: "l9_exchange",
    sender_handle: sender,
    created_at: CREATED,
    episode,
    content: JSON.stringify({
      content: text,
      l9: {
        header: { kind: "exchange", message: { id: "m", parents: [], episode } },
      },
      payload: { type: "message", data: {} },
    }),
  };
}

/** The ping the backend raises into `live` when a thread moves. */
function ping(sender: string, message: string, episode = THREAD) {
  return {
    id: `ping-${message}`,
    message_type: "l9_exchange",
    sender_handle: "system",
    created_at: CREATED,
    episode: LIVE,
    content: JSON.stringify({
      l9: {
        header: { kind: "exchange", message: { id: `ping-${message}`, parents: [], episode: LIVE } },
        payload: { type: "ping", data: { episode, sender, message } },
      },
    }),
  };
}

describe("<EventStream /> and the threads inside the room", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.mocked(fetchMessages).mockResolvedValue({ messages: [] });
    vi.mocked(fetchL9History).mockResolvedValue([]);
    vi.mocked(fetchMemories).mockResolvedValue([]);
  });

  it("keeps a thread's prose out of the channel and shows the ping instead", async () => {
    renderWithSWR(<EventStream roomName={ROOM} />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(said("hold the flip until the lag alarm is green", THREAD));
      es.emit(ping("risk", "m-1"));
    });

    // The argument is not lost, it is placed: `board messages` and the thread
    // pane read it. What the room gets is that the task moved.
    expect(screen.queryByText(/hold the flip/)).not.toBeInTheDocument();
    // What the room gets is that the task moved — in the rail, which is where
    // the room's state lives, not woven through what people are saying.
    expect(await screen.findByText("Recently updated")).toBeInTheDocument();
    expect(screen.getByText("@risk")).toBeInTheDocument();
  });

  it("still shows what was said in the room itself", async () => {
    renderWithSWR(<EventStream roomName={ROOM} />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(said("dual-write is live in staging", LIVE));
      es.emit(said("and the backfill finished", null));
    });

    // The live URN is the room, and so is no episode at all — a message written
    // before threading must not read as a thread nobody can open.
    expect(await screen.findByText("dual-write is live in staging")).toBeInTheDocument();
    expect(screen.getByText("and the backfill finished")).toBeInTheDocument();
  });

  it("collapses a burst from one thread into a single rail entry with its count", async () => {
    renderWithSWR(<EventStream roomName={ROOM} />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(ping("risk", "m-1"));
      es.emit(ping("growth", "m-2"));
      es.emit(ping("risk", "m-3"));
    });

    expect(await screen.findByText("3 updates")).toBeInTheDocument();
    expect(screen.getByText("@risk, @growth")).toBeInTheDocument();
  });

  it("opens the thread a ping names, by URN and not by short id", async () => {
    const onOpenThread = vi.fn();
    renderWithSWR(<EventStream roomName={ROOM} onOpenThread={onOpenThread} />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(ping("risk", "m-1"));
    });

    // No row is bound to this episode, so the name has no details to reach and
    // falls back to the conversation, by URN rather than by the short id it shows.
    await userEvent.click(await screen.findByRole("button", { name: "Open task t3aa11bb" }));
    expect(onOpenThread).toHaveBeenCalledWith(THREAD);
  });

  it("names the task a thread belongs to when the room knows of one", async () => {
    vi.mocked(fetchMemories).mockResolvedValue([
      {
        key: "work/flip-reads-behind-a-flag",
        value: { title: "flip reads behind a flag" },
        version: 1,
        created_by: "aligner",
        updated_at: CREATED,
        episode: THREAD,
      },
    ]);
    renderWithSWR(<EventStream roomName={ROOM} onOpenThread={vi.fn()} />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(ping("risk", "m-1"));
    });

    expect(await screen.findByText("flip reads behind a flag")).toBeInTheDocument();
  });

  it("will not name a thread several rows share", async () => {
    // A converged negotiation binds every task it compiled to the episode it
    // converged in, so there is no one row to name — picking one would be the
    // board asserting something nobody wrote.
    const bound = (key: string, title: string) => ({
      key,
      value: { title },
      version: 1,
      created_by: "aligner",
      updated_at: CREATED,
      episode: THREAD,
    });
    vi.mocked(fetchMemories).mockResolvedValue([
      bound("work/flip-reads-behind-a-flag", "flip reads behind a flag"),
      bound("work/retire-the-legacy-store", "retire the legacy store"),
    ]);
    renderWithSWR(<EventStream roomName={ROOM} onOpenThread={vi.fn()} />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(ping("risk", "m-1"));
    });

    expect(await screen.findByText("t3aa11bb")).toBeInTheDocument();
    expect(screen.queryByText("retire the legacy store")).not.toBeInTheDocument();
  });

  it("falls back to the thread's short id when no row is bound to it", async () => {
    // A coordination phase opens its own episode and records no back-link to the
    // task that summoned it, so this is the honest read, not a gap to paper over.
    renderWithSWR(<EventStream roomName={ROOM} onOpenThread={vi.fn()} />);
    await act(async () => {});
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(ping("aligner", "m-1"));
    });

    expect(await screen.findByText("t3aa11bb")).toBeInTheDocument();
  });

  it("recovers the pings on a cold read, where the message list has none", async () => {
    // A ping is a control frame, so the conversational read drops it; only the
    // transcript's L9 replay keeps it. Without merging both, a reload would show
    // a quiet room that had been busy all morning.
    vi.mocked(fetchMessages).mockResolvedValue({ messages: [said("morning", LIVE, "operator")] });
    vi.mocked(fetchL9History).mockResolvedValue([ping("risk", "m-1")]);

    renderWithSWR(<EventStream roomName={ROOM} />);
    await act(async () => {});

    expect(await screen.findByText("morning")).toBeInTheDocument();
    expect(screen.getByText("Recently updated")).toBeInTheDocument();
  });

  it("takes only the pings from the L9 replay, so nothing lands twice", async () => {
    // Every other frame in that replay already reaches the feed as a message.
    const knowledge = {
      id: "k-1",
      message_type: "l9_knowledge",
      sender_handle: "system",
      created_at: CREATED,
      episode: LIVE,
      content: JSON.stringify({
        content: "memory updated → work/flip",
        l9: { payload: { type: "extraction", data: { key: "work/flip" } } },
      }),
    };
    vi.mocked(fetchMessages).mockResolvedValue({ messages: [knowledge] });
    vi.mocked(fetchL9History).mockResolvedValue([knowledge]);

    renderWithSWR(<EventStream roomName={ROOM} />);
    await act(async () => {});

    // One update, not two: the L9 replay and the message list both carry this
    // frame, and a rail that counted it twice would report a duplicate as work.
    expect(await screen.findByText("1 update")).toBeInTheDocument();
  });
});
