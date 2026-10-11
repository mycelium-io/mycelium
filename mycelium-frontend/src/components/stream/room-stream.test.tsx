// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const THREAD = "urn:ioc:mycelium:episode:sprint:t1";
const at = (m: number) => `2026-10-11T20:${String(m).padStart(2, "0")}:00Z`;

const history = [
  {
    id: "n1",
    sender_handle: "system",
    message_type: "l9_exchange",
    created_at: at(1),
    content: JSON.stringify({
      l9: { payload: { type: "notice", data: { subkind: "filed", key: "work/zoom", title: "Zoom and pan", episode: THREAD, by: "chat-buddy" } } },
    }),
  },
  { id: "m1", sender_handle: "alice", message_type: "broadcast", created_at: at(2), content: "morning all" },
  { id: "m2", sender_handle: "builder", message_type: "broadcast", created_at: at(3), episode: THREAD, content: "@bob which preset?\n\nZed or VS Code." },
];

vi.mock("@/lib/api", () => ({
  fetchWireHistory: vi.fn(async () => history),
  logFetchError: () => () => {},
}));
vi.mock("@/lib/stream-hub", () => ({ useRoomStream: () => {} }));
vi.mock("@/lib/room-data", () => ({
  useRoomThreads: () => new Map([[THREAD, { keys: ["work/zoom"], title: "Zoom and pan" }]]),
}));
vi.mock("@/components/current-user", () => ({ useCurrentUser: () => ({ principal: "bob" }) }));
vi.mock("@/components/room-chat-box", () => ({
  RoomChatBox: ({ episode }: { episode: string | null }) => <div data-testid="composer">{episode ?? "channel"}</div>,
}));
vi.mock("@/components/message-body", () => ({ MessageBody: ({ content }: { content: string }) => <div>{content}</div> }));

import { RoomStream } from "@/components/stream/room-stream";

async function renderStream(onOpenThread = vi.fn()) {
  render(<RoomStream roomName="sprint" onOpenThread={onOpenThread} />);
  await act(async () => {});
  return onOpenThread;
}

describe("<RoomStream />", () => {
  beforeEach(() => window.localStorage.clear());

  it("shows the channel, threads and board changes in one time-ordered log", async () => {
    await renderStream();
    const log = screen.getByRole("log");
    const text = log.textContent ?? "";
    expect(text.indexOf("filed")).toBeLessThan(text.indexOf("morning all"));
    expect(text.indexOf("morning all")).toBeLessThan(text.indexOf("which preset?"));
  });

  it("filters to messages that mention you", async () => {
    const user = userEvent.setup();
    await renderStream();
    await user.click(screen.getByRole("button", { name: "@bob" }));
    expect(screen.queryByText("morning all")).not.toBeInTheDocument();
    expect(screen.getByText(/which preset\?/)).toBeInTheDocument();
  });

  it("opens a message in place and points the box at its thread", async () => {
    const user = userEvent.setup();
    await renderStream();
    expect(screen.getByTestId("composer")).toHaveTextContent("channel");
    await user.click(screen.getByText(/which preset\?/));
    expect(screen.getByText(/Zed or VS Code/)).toBeInTheDocument();
    expect(screen.getByTestId("composer")).toHaveTextContent(THREAD);
    await user.click(screen.getByRole("button", { name: /Back to the channel/ }));
    expect(screen.getByTestId("composer")).toHaveTextContent("channel");
  });

  it("opens a task's thread from its tag", async () => {
    const user = userEvent.setup();
    const onOpenThread = await renderStream();
    await user.click(screen.getAllByRole("button", { name: "Zoom and pan" })[0]);
    expect(onOpenThread).toHaveBeenCalledWith(THREAD);
  });
});
