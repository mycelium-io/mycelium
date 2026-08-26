// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// What the room's timeline does with its own bookkeeping.
//
// A task moving raises three different frames — a board notice, a memory push,
// a thread ping — and each is worth keeping. Printed one per line they bury the
// conversation they accompany, so the feed condenses them into one block per
// task and opens it on demand. These cases are about that block: that it forms,
// that it names the task rather than its slug, and that nothing folded into it
// is lost.

import { act } from "react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithSWR } from "@/test/swr";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";
import { fetchL9History, fetchMessages, fetchMemories } from "@/lib/api";
import { ACTIVITY_WINDOW_MS } from "@/lib/threads";

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
const TASK = "work/flip-reads-behind-a-flag";
const TITLE = "flip reads behind a flag";
const T0 = Date.parse("2026-08-26T10:00:00.000Z");
const at = (offsetMs = 0) => new Date(T0 + offsetMs).toISOString();

/** The board row the three frames below are all about. */
const row = {
  key: TASK,
  value: { title: TITLE },
  version: 3,
  created_by: "aligner",
  updated_at: at(),
  episode: THREAD,
};

function notice(subkind: string, by: string, offsetMs = 0) {
  return {
    id: `notice-${subkind}`,
    message_type: "l9_exchange",
    sender_handle: "system",
    created_at: at(offsetMs),
    episode: LIVE,
    content: JSON.stringify({
      l9: {
        payload: {
          type: "notice",
          data: { subkind, key: TASK, title: TITLE, episode: THREAD, by, kind: "action" },
        },
      },
    }),
  };
}

function knowledge(version: number, updatedBy: string, offsetMs = 0) {
  return {
    id: `knowledge-${version}`,
    message_type: "l9_knowledge",
    sender_handle: "system",
    created_at: at(offsetMs),
    episode: LIVE,
    content: JSON.stringify({
      content: `memory updated → ${TASK}`,
      l9: { payload: { type: "extraction", data: { key: TASK, updated_by: updatedBy, version } } },
    }),
  };
}

function ping(sender: string, message: string, offsetMs = 0) {
  return {
    id: `ping-${message}`,
    message_type: "l9_exchange",
    sender_handle: "system",
    created_at: at(offsetMs),
    episode: LIVE,
    content: JSON.stringify({
      l9: { payload: { type: "ping", data: { episode: THREAD, sender, message } } },
    }),
  };
}

function said(text: string, sender = "operator", offsetMs = 0) {
  return {
    id: `said-${text.length}`,
    message_type: "l9_exchange",
    sender_handle: sender,
    created_at: at(offsetMs),
    episode: LIVE,
    content: JSON.stringify({ content: text, l9: { payload: { type: "message", data: {} } } }),
  };
}

describe("<EventStream /> and the room's own bookkeeping", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.mocked(fetchMessages).mockResolvedValue({ messages: [] });
    vi.mocked(fetchL9History).mockResolvedValue([]);
    vi.mocked(fetchMemories).mockResolvedValue([row]);
  });

  async function stream(frames: Record<string, unknown>[]) {
    renderWithSWR(<EventStream roomName={ROOM} onOpenThread={vi.fn()} />);
    await act(async () => {});
    const es = FakeEventSource.latest();
    await act(async () => {
      es.open();
      for (const frame of frames) es.emit(frame);
    });
  }

  it("folds a notice, a memory push and a ping about one task into a single block", async () => {
    await stream([
      notice("filed", "growth"),
      knowledge(1, "claude-web", 500),
      ping("growth", "m-1", 900),
    ]);

    expect(await screen.findByText("· 3 updates")).toBeInTheDocument();
    // The task's name, once — not its slug three times in three shapes.
    expect(screen.getByText(TITLE)).toBeInTheDocument();
    expect(screen.queryByText(TASK)).not.toBeInTheDocument();
    expect(screen.getByText("· @growth, @claude-web")).toBeInTheDocument();
  });

  it("keeps folding across what is said in between, and leaves the talk where it was", async () => {
    await stream([
      knowledge(1, "claude-web"),
      said("what happened to the flag?", "operator", 400),
      knowledge(2, "claude-web", 800),
      knowledge(3, "growth", 1200),
    ]);

    expect(await screen.findByText("· 3 updates")).toBeInTheDocument();
    expect(screen.getByText("what happened to the flag?")).toBeInTheDocument();
  });

  it("opens the block to the events it stands for, so nothing is hidden", async () => {
    await stream([
      notice("filed", "growth"),
      notice("claimed", "growth", 400),
      knowledge(2, "claude-web", 800),
    ]);

    await userEvent.click(await screen.findByRole("button", { name: "Show 3 updates" }));

    expect(screen.getByText("New task")).toBeInTheDocument();
    expect(screen.getByText("Claimed")).toBeInTheDocument();
    expect(screen.getByText("v2 · @claude-web")).toBeInTheDocument();
  });

  it("says so again once the window has closed, rather than only counting higher", async () => {
    await stream([
      knowledge(1, "claude-web"),
      knowledge(2, "claude-web", 1000),
      knowledge(3, "claude-web", ACTIVITY_WINDOW_MS + 1000),
    ]);

    expect(await screen.findByText("· 2 updates")).toBeInTheDocument();
    expect(screen.getByText("Knowledge")).toBeInTheDocument();
  });

  it("keeps two tasks apart", async () => {
    const other = {
      id: "notice-other",
      message_type: "l9_exchange",
      sender_handle: "system",
      created_at: at(400),
      episode: LIVE,
      content: JSON.stringify({
        l9: {
          payload: {
            type: "notice",
            data: { subkind: "filed", key: "work/retire-the-legacy-store", title: "48h soak, then retire the legacy store", by: "ops", kind: "action" },
          },
        },
      }),
    };
    await stream([notice("filed", "growth"), other, knowledge(2, "claude-web", 800)]);

    expect(await screen.findByText("· 2 updates")).toBeInTheDocument();
    expect(screen.getByText("48h soak, then retire the legacy store")).toBeInTheDocument();
  });
});
