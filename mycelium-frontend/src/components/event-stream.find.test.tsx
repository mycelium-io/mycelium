// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { screen, within } from "@testing-library/react";
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

function chat(text: string, sender = "alice") {
  return {
    message_type: "broadcast",
    sender_handle: sender,
    created_at: CREATED,
    content: text,
  };
}

/** Mount the channel with a room already said, then open find on it. */
async function openFind(lines: [string, string?][]) {
  const view = renderWithSWR(<EventStream roomName="sprint" openFind={0} />);
  await act(async () => {});
  const es = FakeEventSource.latest();
  await act(async () => {
    es.open();
    for (const [text, sender] of lines) es.emit(chat(text, sender));
  });
  // The room page owns ⌘F; what reaches the channel is the bumped counter.
  view.rerender(<EventStream roomName="sprint" openFind={1} />);
  await act(async () => {});
  return view;
}

const findBar = () => screen.getByLabelText("Find in the channel");
const status = () => screen.getByRole("button", { name: "Close find" }).closest("[data-slot='chat-find-bar']")!;

describe("<EventStream /> find in the channel", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("stays out of the way until the room's ⌘F asks for it", async () => {
    renderWithSWR(<EventStream roomName="sprint" />);
    await act(async () => {});

    expect(screen.queryByLabelText("Find in the channel")).not.toBeInTheDocument();
  });

  it("opens on the room's find request and takes focus", async () => {
    await openFind([["the deploy is stuck"]]);

    expect(findBar()).toHaveFocus();
  });

  it("counts the messages a query hits and marks the text in them", async () => {
    await openFind([
      ["the deploy is stuck"],
      ["unrelated chatter"],
      ["deploy again after the fix"],
    ]);

    await userEvent.type(findBar(), "deploy");

    // Two messages, and the reader starts on the newest — the end of the feed
    // is where they were standing when they pressed the key.
    expect(within(status() as HTMLElement).getByText("2/2")).toBeInTheDocument();
    expect(screen.getAllByText("deploy", { selector: "mark" })).toHaveLength(2);
  });

  it("marks the message it has stepped to differently from the rest", async () => {
    await openFind([["deploy one"], ["deploy two"]]);
    await userEvent.type(findBar(), "deploy");

    const marks = screen.getAllByText("deploy", { selector: "mark" });
    expect(marks.map(m => m.dataset.findMatch)).toEqual(["hit", "active"]);
  });

  it("steps between matches with wrap-around", async () => {
    await openFind([["deploy one"], ["deploy two"]]);
    await userEvent.type(findBar(), "deploy");
    const bar = status() as HTMLElement;

    expect(within(bar).getByText("2/2")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Next match"));
    expect(within(bar).getByText("1/2")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Previous match"));
    expect(within(bar).getByText("2/2")).toBeInTheDocument();
  });

  it("finds a sender by name, not only what they said", async () => {
    await openFind([["nothing to see", "alice"], ["also nothing", "bruno"]]);

    await userEvent.type(findBar(), "bruno");

    expect(within(status() as HTMLElement).getByText("1/1")).toBeInTheDocument();
  });

  it("says so plainly when a query hits nothing", async () => {
    await openFind([["the deploy is stuck"]]);

    await userEvent.type(findBar(), "kubernetes");

    expect(screen.getByText("No matches")).toBeInTheDocument();
    expect(screen.queryByText("kubernetes", { selector: "mark" })).not.toBeInTheDocument();
  });

  it("matches the query literally, so a metacharacter is not a pattern", async () => {
    await openFind([["cost is $5 (net)"]]);

    await userEvent.type(findBar(), "(net)");

    expect(within(status() as HTMLElement).getByText("1/1")).toBeInTheDocument();
  });

  it("closes on Escape and takes its marks with it", async () => {
    await openFind([["the deploy is stuck"]]);
    await userEvent.type(findBar(), "deploy");
    expect(screen.getAllByText("deploy", { selector: "mark" })).toHaveLength(1);

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByLabelText("Find in the channel")).not.toBeInTheDocument();
    expect(screen.queryByText("deploy", { selector: "mark" })).not.toBeInTheDocument();
    expect(screen.getByText("the deploy is stuck")).toBeInTheDocument();
  });

  it("marks a hit inside an @mention, which is prose too", async () => {
    await openFind([["ping @growth about the soak"]]);

    await userEvent.type(findBar(), "growth");

    // The mention renders as its own styled span; a find that skipped it would
    // count a message it could not show the reader anything in.
    expect(screen.getByText("growth", { selector: "mark" })).toBeInTheDocument();
  });

  it("claims no limit it doesn't have once the whole room is loaded", async () => {
    await openFind([["the deploy is stuck"]]);
    await userEvent.type(findBar(), "deploy");

    // This channel has walked back to the beginning of the room, so find has
    // genuinely searched all of it. (The reverse — a channel with pages it
    // hasn't read saying so — is ChatFindBar's own test.)
    expect(screen.queryByText("loaded only")).not.toBeInTheDocument();
  });

  it("puts a tick in the scroll gutter for every match", async () => {
    await openFind([["deploy one"], ["quiet"], ["deploy two"]]);
    await userEvent.type(findBar(), "deploy");

    expect(screen.getByLabelText("Jump to match 1 of 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Jump to match 2 of 2")).toBeInTheDocument();
  });

  it("jumps to the match whose tick is clicked", async () => {
    await openFind([["deploy one"], ["deploy two"]]);
    await userEvent.type(findBar(), "deploy");
    expect(within(status() as HTMLElement).getByText("2/2")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Jump to match 1 of 2"));

    expect(within(status() as HTMLElement).getByText("1/2")).toBeInTheDocument();
  });
});
