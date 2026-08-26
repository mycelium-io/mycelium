// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// What the room's own bookkeeping does to the conversation.
//
// A task being worked writes memory, pings its thread and moves on the board,
// and none of that is something anybody said. Taken from a live capture of the
// hub's own room: ninety minutes, seven agents, 76 system lines and not one
// sentence of speech. These cases pin the split that makes that legible — the
// churn goes to the rail, the transitions worth narrating stay in the feed, and
// the roster's own writes appear in neither.

import { act } from "react";
import { screen, within } from "@testing-library/react";
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
  logFetchError: () => () => undefined,
}));

import { EventStream } from "@/components/event-stream";

const ROOM = "atlas";
const LIVE = "urn:ioc:mycelium:episode:atlas:live";
const THREAD = "urn:ioc:mycelium:episode:atlas:t3aa11bb";
const TASK = "work/flip-reads-behind-a-flag";
const TITLE = "flip reads behind a flag";
const OTHER_TASK = "work/retire-the-legacy-store";
const OTHER_TITLE = "48h soak, then retire the legacy store";
const T0 = Date.parse("2026-08-26T10:00:00.000Z");
const at = (offsetMs = 0) => new Date(T0 + offsetMs).toISOString();

const row = (key: string, title: string, episode: string | null) => ({
  key,
  value: { title },
  version: 3,
  created_by: "aligner",
  updated_at: at(),
  ...(episode ? { episode } : {}),
});

function notice(subkind: string, by: string, offsetMs = 0, key = TASK, title = TITLE) {
  return {
    id: `notice-${subkind}-${key}`,
    message_type: "l9_exchange",
    sender_handle: "system",
    created_at: at(offsetMs),
    episode: LIVE,
    content: JSON.stringify({
      l9: {
        payload: {
          type: "notice",
          data: { subkind, key, title, episode: THREAD, by, kind: "action" },
        },
      },
    }),
  };
}

function knowledge(version: number, updatedBy: string, offsetMs = 0, key = TASK) {
  return {
    id: `knowledge-${key}-${version}`,
    message_type: "l9_knowledge",
    sender_handle: "system",
    created_at: at(offsetMs),
    episode: LIVE,
    content: JSON.stringify({
      content: `memory updated → ${key}`,
      l9: { payload: { type: "extraction", data: { key, updated_by: updatedBy, version } } },
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

/** The rail, as a scope to query inside. */
const rail = () => screen.getByText("Recently updated").closest("div")!.parentElement!;

describe("<EventStream /> and the room's own bookkeeping", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.mocked(fetchMessages).mockResolvedValue({ messages: [] });
    vi.mocked(fetchL9History).mockResolvedValue([]);
    vi.mocked(fetchMemories).mockResolvedValue([
      row(TASK, TITLE, THREAD),
      row(OTHER_TASK, OTHER_TITLE, null),
    ]);
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

  it("gathers a task's whole run of churn into one rail entry, not a line each", async () => {
    await stream([
      knowledge(1, "claude-web"),
      ping("growth", "m-1", 500),
      notice("claimed", "growth", 900),
      knowledge(2, "growth", 1400),
      ping("risk", "m-2", 1900),
    ]);

    const entry = await screen.findByRole("button", { name: new RegExp(TITLE) });
    expect(within(entry).getByText("5 updates")).toBeInTheDocument();
    expect(within(entry).getByText("@claude-web, @growth, @risk")).toBeInTheDocument();
  });

  it("keeps every one of those out of the conversation", async () => {
    await stream([
      knowledge(1, "claude-web"),
      ping("growth", "m-1", 500),
      notice("claimed", "growth", 900),
      said("so where did we land on the flag?", "operator", 1200),
    ]);

    // The one thing anybody said is the one thing in the feed.
    expect(await screen.findByText("so where did we land on the flag?")).toBeInTheDocument();
    expect(screen.queryByText("Knowledge")).not.toBeInTheDocument();
    expect(screen.queryByText("Activity")).not.toBeInTheDocument();
    expect(screen.queryByText("Claimed")).not.toBeInTheDocument();
  });

  it("still narrates a task arriving and finishing, in sequence with the talk", async () => {
    await stream([
      notice("filed", "aligner"),
      said("taking this one", "growth", 400),
      notice("resolved", "growth", 800),
    ]);

    expect(await screen.findByText("New task")).toBeInTheDocument();
    expect(screen.getByText("Resolved")).toBeInTheDocument();
    expect(screen.getByText("taking this one")).toBeInTheDocument();
  });

  it("folds a run of arrivals by what happened, not by which task", async () => {
    // Several tasks filed in the same minute is one thing the room did. Naming
    // the run "New task" would report all of them as one of them.
    await stream([
      notice("filed", "aligner", 0, TASK, TITLE),
      notice("filed", "aligner", 300, OTHER_TASK, OTHER_TITLE),
    ]);

    expect(await screen.findByText("New tasks")).toBeInTheDocument();
    expect(screen.queryByText("New task")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show 2 updates" }));
    expect(screen.getByRole("button", { name: new RegExp(OTHER_TITLE) })).toBeInTheDocument();
  });

  it("will not fold an arrival into an outcome", async () => {
    // Same task, same run of notices — but filed and resolved are two different
    // pieces of news, and one line would report the second as the first.
    await stream([notice("filed", "aligner"), notice("resolved", "growth", 400)]);

    expect(await screen.findByText("New task")).toBeInTheDocument();
    expect(screen.getByText("Resolved")).toBeInTheDocument();
  });

  it("leaves an agent's own manifest write out of both surfaces", async () => {
    // Seven agents joining is otherwise seven lines saying somebody arrived,
    // and the Members rail already says it.
    await stream([
      knowledge(1, "claude-web", 0, "agents/task-886"),
      said("morning", "operator", 400),
    ]);

    expect(await screen.findByText("morning")).toBeInTheDocument();
    expect(screen.queryByText("Recently updated")).not.toBeInTheDocument();
    expect(screen.queryByText(/agents\/task-886/)).not.toBeInTheDocument();
  });

  it("holds the rail to a fixed height however many tasks are moving", async () => {
    const keys = ["a", "b", "c", "d", "e"];
    vi.mocked(fetchMemories).mockResolvedValue(keys.map(k => row(`work/${k}`, `task ${k}`, null)));
    await stream(keys.map((k, i) => knowledge(1, "claude-web", i * 100, `work/${k}`)));

    expect(await screen.findByText("5 tasks")).toBeInTheDocument();
    // Three rows stand open and the rest are behind one control, so a busy hour
    // costs the same height as a quiet one.
    expect(within(rail()).getAllByRole("button", { name: /^task / })).toHaveLength(3);
    await userEvent.click(screen.getByRole("button", { name: "Show all 5" }));
    expect(within(rail()).getAllByRole("button", { name: /^task / })).toHaveLength(5);
  });

  it("orders the rail by what moved last", async () => {
    await stream([
      knowledge(1, "claude-web", 0, TASK),
      knowledge(1, "claude-web", 500, OTHER_TASK),
    ]);

    const rows = within(rail()).getAllByRole("button", { name: /flag|legacy store/ });
    expect(rows[0]).toHaveAccessibleName(new RegExp(OTHER_TITLE));
  });
});
