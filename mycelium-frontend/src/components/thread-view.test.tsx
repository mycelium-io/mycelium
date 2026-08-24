// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithSWR } from "@/test/swr";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

const fetchMessages = vi.fn();
const sendRoomMessage = vi.fn().mockResolvedValue(undefined);

vi.mock("@/lib/api", () => ({
  logFetchError: () => () => undefined,
  fetchMessages: (...args: unknown[]) => fetchMessages(...args),
  sendRoomMessage: (...args: unknown[]) => sendRoomMessage(...args),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchRoomMembers: vi.fn().mockResolvedValue([]),
  fetchMemories: vi.fn().mockResolvedValue([]),
  fetchSkills: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia" }),
}));

vi.mock("@/components/keymap-provider", () => ({
  useKeyAction: () => undefined,
}));

import { ThreadView } from "@/components/thread-view";

const THREAD = "urn:ioc:mycelium:episode:atlas:t3aa11bb";

/** The backend answers newest-first; a conversation reads the other way. */
const NEWEST_FIRST = {
  messages: [
    { id: "m2", sender_handle: "growth", content: "agreed, gating on the lag alarm", created_at: "2026-08-04T10:01:00+00:00" },
    { id: "m1", sender_handle: "risk", content: "hold the flip until lag is under a second", created_at: "2026-08-04T10:00:00+00:00" },
  ],
};

describe("<ThreadView />", () => {
  beforeEach(() => {
    fetchMessages.mockReset().mockResolvedValue(NEWEST_FIRST);
    sendRoomMessage.mockClear();
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("reads only its own episode, and says so on the wire", async () => {
    renderWithSWR(
      <ThreadView roomName="atlas" target={{ episode: THREAD }} onClose={vi.fn()} />,
    );
    await screen.findByText(/hold the flip/);
    // The narrowing is the server's, not a filter over the room's feed: a pane
    // that fetched everything and hid most of it would page in the room's noise
    // to show one task's conversation.
    expect(fetchMessages).toHaveBeenCalledWith("atlas", expect.any(Number), { episode: THREAD });
  });

  it("reads the conversation oldest-first", async () => {
    renderWithSWR(
      <ThreadView roomName="atlas" target={{ episode: THREAD }} onClose={vi.fn()} />,
    );
    const said = await screen.findAllByText(/lag/);
    expect(said[0]).toHaveTextContent("hold the flip until lag is under a second");
  });

  it("names the task it belongs to, and falls back to the thread when nothing does", async () => {
    const { unmount } = renderWithSWR(
      <ThreadView roomName="atlas" target={{ episode: THREAD, title: "flip reads behind a flag" }} onClose={vi.fn()} />,
    );
    expect(await screen.findByText("flip reads behind a flag")).toBeInTheDocument();
    unmount();

    renderWithSWR(<ThreadView roomName="atlas" target={{ episode: THREAD }} onClose={vi.fn()} />);
    expect(await screen.findByText("Thread t3aa11bb")).toBeInTheDocument();
  });

  it("posts into its own episode, not into the room", async () => {
    renderWithSWR(
      <ThreadView roomName="atlas" target={{ episode: THREAD, title: "flip reads" }} onClose={vi.fn()} />,
    );
    const box = await screen.findByPlaceholderText(/Reply in flip reads/);
    await userEvent.type(box, "flag is wired{Enter}");
    await waitFor(() => expect(sendRoomMessage).toHaveBeenCalled());
    expect(sendRoomMessage.mock.calls[0][1]).toMatchObject({ episode: THREAD });
  });

  it("closes on Esc and on the close button, because it is a pane and not a rail", async () => {
    const onClose = vi.fn();
    renderWithSWR(
      <ThreadView roomName="atlas" target={{ episode: THREAD }} onClose={onClose} />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Close thread" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("does not close on Esc typed into the composer", async () => {
    // Esc there dismisses the completion popover; stealing it would close the
    // pane out from under someone mid-sentence.
    const onClose = vi.fn();
    renderWithSWR(
      <ThreadView roomName="atlas" target={{ episode: THREAD }} onClose={onClose} />,
    );
    const box = await screen.findByPlaceholderText(/Reply in/);
    await userEvent.click(box);
    await userEvent.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("shows what was said, not the frames a thread also carries", async () => {
    // A join, a mediator tick and the commit it converged on are the thread's
    // lifecycle, not things anybody said — the row's own state is where that
    // reads, and echoing them here would be a conversation full of blanks.
    fetchMessages.mockResolvedValue({
      messages: [
        { id: "c1", sender_handle: "aligner", message_type: "coordination_consensus", content: JSON.stringify({ assignments: { window: "48h" } }), created_at: "2026-08-04T10:02:00+00:00" },
        { id: "m1", sender_handle: "risk", content: "hold the flip until lag is under a second", created_at: "2026-08-04T10:00:00+00:00" },
      ],
    });
    renderWithSWR(
      <ThreadView roomName="atlas" target={{ episode: THREAD }} onClose={vi.fn()} />,
    );
    expect(await screen.findByText(/hold the flip/)).toBeInTheDocument();
    expect(screen.queryByText("aligner")).not.toBeInTheDocument();
  });

  it("says a quiet thread is quiet rather than looking broken", async () => {
    fetchMessages.mockResolvedValue({ messages: [] });
    renderWithSWR(
      <ThreadView roomName="atlas" target={{ episode: THREAD }} onClose={vi.fn()} />,
    );
    expect(await screen.findByText("Nothing said here yet")).toBeInTheDocument();
  });

  it("re-reads when a write lands in its own thread, and not when one lands elsewhere", async () => {
    // The pane is a read of one episode, so a live write is a reason to re-read
    // rather than something to append by hand — and a busy room next door is not
    // a reason at all.
    renderWithSWR(
      <ThreadView roomName="atlas" target={{ episode: THREAD }} onClose={vi.fn()} />,
    );
    await screen.findByText(/hold the flip/);
    const reads = fetchMessages.mock.calls.length;
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit({ message_type: "broadcast", sender_handle: "ops", content: "unrelated", episode: "urn:ioc:mycelium:episode:atlas:live" });
    });
    expect(fetchMessages.mock.calls.length).toBe(reads);

    await act(async () => {
      es.emit({ message_type: "broadcast", sender_handle: "risk", content: "one more thing", episode: THREAD });
    });
    await waitFor(() => expect(fetchMessages.mock.calls.length).toBe(reads + 1));
  });

  it("re-reads on the ping that announces a write into it", async () => {
    // The ping rides in `live` and names this thread in its payload, so the two
    // ways a write reaches the stream both land the pane on the same re-read.
    renderWithSWR(
      <ThreadView roomName="atlas" target={{ episode: THREAD }} onClose={vi.fn()} />,
    );
    await screen.findByText(/hold the flip/);
    const reads = fetchMessages.mock.calls.length;
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit({
        message_type: "l9_exchange",
        sender_handle: "system",
        episode: "urn:ioc:mycelium:episode:atlas:live",
        content: JSON.stringify({
          l9: { payload: { type: "ping", data: { episode: THREAD, sender: "risk", message: "m3" } } },
        }),
      });
    });
    await waitFor(() => expect(fetchMessages.mock.calls.length).toBe(reads + 1));
  });
});
