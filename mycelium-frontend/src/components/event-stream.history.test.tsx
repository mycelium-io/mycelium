// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** The find bar's History: the room-wide search behind the bar, and what a
 *  hit in it does. */

import { act } from "react";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithSWR } from "@/test/swr";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";
import type { MessageSearchResponse } from "@/lib/message-search";

const searchMessages = vi.fn();

vi.mock("@/lib/api", () => ({
  fetchMessages: vi.fn().mockResolvedValue({ messages: [] }),
  fetchUsers: vi.fn().mockResolvedValue([]),
  fetchL9History: vi.fn().mockResolvedValue([]),
  fetchMemories: vi.fn().mockResolvedValue([]),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  searchMessages: (...args: unknown[]) => searchMessages(...args),
  logFetchError: () => () => undefined,
}));

import { EventStream } from "@/components/event-stream";

const CREATED = "2026-08-04T10:00:00.000000+00:00";
const THREAD = "urn:ioc:mycelium:episode:sprint:abc123";

function said(id: string, text: string, sender = "alice") {
  return { id, message_type: "broadcast", sender_handle: sender, created_at: CREATED, content: text };
}

function answer(over: Partial<MessageSearchResponse> = {}): MessageSearchResponse {
  return {
    query: "",
    scope: { text: "", clauses: [], after: null, before: null, sort: "newest", problems: [] },
    hits: [],
    total: 0,
    scanned: 3,
    facets: {},
    fields: [],
    next_cursor: null,
    ...over,
  };
}

function hit(id: string, text: string, sender: string, thread: string | null = null) {
  return {
    message: { ...said(id, text, sender), room_name: "sprint", episode: thread },
    snippet: text,
    score: 1,
    task_key: thread ? "work/ship" : null,
    task_title: thread ? "Ship the release" : null,
    thread,
    recipients: [],
    mentions: [],
    stance: null,
    context_before: [],
    context_after: [],
  };
}

async function openFind(onOpenThread = vi.fn()) {
  const view = renderWithSWR(<EventStream roomName="sprint" openFind={0} onOpenThread={onOpenThread} />);
  await act(async () => {});
  const es = FakeEventSource.latest();
  await act(async () => {
    es.open();
    es.emit(said("m1", "the deploy is stuck", "alice"));
    es.emit(said("m2", "looking at it", "bruno"));
  });
  view.rerender(<EventStream roomName="sprint" openFind={1} onOpenThread={onOpenThread} />);
  await act(async () => {});
  return { onOpenThread };
}

/** Let typing settle, the way the bar waits before asking the hub. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 260));
  });
}

const findBar = () => screen.getByLabelText("Find in the channel");
const history = () => screen.getByRole("region", { name: "Search the room's history" });

describe("<EventStream /> find: the room's whole history", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
    searchMessages.mockReset();
  });

  it("asks the hub, lists every hit with where it was said, and narrows by a count", async () => {
    searchMessages.mockResolvedValue(
      answer({
        total: 2,
        hits: [hit("t1", "deploy blocked on review", "bruno", THREAD), hit("m1", "the deploy is stuck", "alice")],
        facets: { from: [{ value: "alice", label: "alice", count: 1 }, { value: "bruno", label: "bruno", count: 1 }] },
      }),
    );
    await openFind();
    await userEvent.type(findBar(), "deploy");
    await settle();

    expect(searchMessages).toHaveBeenLastCalledWith("sprint", "deploy", { limit: 50 });
    const list = within(history()).getByRole("list", { name: "Matching messages" });
    expect(within(list).getByText("Ship the release")).toBeInTheDocument();
    expect(within(list).getAllByRole("button")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Search history, 2 matches" })).toBeInTheDocument();

    // A count is a switch: on adds the clause to the query, and the bar says so.
    await userEvent.click(within(history()).getByTitle("from:bruno"));
    expect(findBar()).toHaveValue("deploy from:bruno");
  });

  it("opens the task's thread for a hit said inside one", async () => {
    searchMessages.mockResolvedValue(answer({ total: 1, hits: [hit("t1", "deploy blocked", "bruno", THREAD)] }));
    const { onOpenThread } = await openFind();
    await userEvent.type(findBar(), "blocked");
    await settle();

    await userEvent.click(within(history()).getByRole("button", { name: /deploy blocked/ }));
    expect(onOpenThread).toHaveBeenCalledWith(THREAD);
  });

  it("steps through the loaded messages a fields-only query returned", async () => {
    searchMessages.mockResolvedValue(answer({ total: 1, hits: [hit("m2", "looking at it", "bruno")] }));
    await openFind();
    await userEvent.type(findBar(), "from:bruno ");
    await settle();

    const bar = screen.getByRole("button", { name: "Close find" }).closest("[data-slot='chat-find-bar']") as HTMLElement;
    expect(within(bar).getByText("1/1")).toBeInTheDocument();
  });
});
