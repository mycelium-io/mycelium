// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import type { RoomMessage } from "@/lib/api";

/** What the thread read answers; a refresh hands back a new array of the same messages. */
let messages: RoomMessage[] = [];
const said = (id: string, content: string, at: string) =>
  ({ id, sender_handle: "builder", message_type: "broadcast", content, created_at: at }) as RoomMessage;

vi.mock("@/lib/room-data", () => ({
  useThreadMessages: () => ({
    messages,
    loading: false,
    refresh: vi.fn(),
    hasOlder: false,
    loadOlder: vi.fn(),
    loadingOlder: false,
  }),
  useRoomAgents: () => ({ agents: [{ handle: "builder", adapter: "claude_code" }] }),
  useRoomVerifierFlags: () => ({ byMessage: new Map(), refresh: vi.fn() }),
  useRoomThreads: () => new Map(),
  useRoomRowNames: () => new Map(),
}));
vi.mock("@/components/message-actions", () => ({ MessageActions: () => null }));
vi.mock("@/lib/stream-hub", () => ({ useRoomStream: vi.fn() }));
vi.mock("@/lib/pending-messages", () => ({ usePendingMessages: () => [], resetPending: vi.fn() }));
vi.mock("@/components/pending-message-rows", () => ({ PendingMessageRows: () => null }));
vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: { handle: "julia" } }),
}));
/** Mounts of a message's body: its own state (an expanded Show more) lives as long as one mount. */
const mounts: string[] = [];
vi.mock("@/components/message-body", () => ({
  MessageBody: ({ content }: { content: string }) => {
    useEffect(() => {
      mounts.push(content);
      // Counts mounts, not renders.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return <p>{content}</p>;
  },
}));

const { TaskConversation } = await import("./task-conversation");

describe("TaskConversation on a refresh", () => {
  it("keeps every row, so an expanded message stays expanded and the page doesn't jump", () => {
    messages = [said("m2", "Second.", "2026-10-17T10:01:00Z"), said("m1", "First.", "2026-10-17T10:00:00Z")];
    const onRows = vi.fn();
    const { rerender } = render(<TaskConversation roomName="r" episode="urn:ep" onRows={onRows} />);
    expect(mounts).toEqual(["First.", "Second."]);
    const firstRows = onRows.mock.calls.at(-1)?.[0].rows;
    expect(firstRows).toEqual(["m1", "m2"]);

    // The poll answers again with the same messages, in a new array.
    messages = messages.map((m) => ({ ...m }));
    rerender(<TaskConversation roomName="r" episode="urn:ep" onRows={onRows} />);
    expect(mounts).toEqual(["First.", "Second."]);
    // Following the latest sees the same rows, not a thread of new ones.
    expect(onRows.mock.calls.at(-1)?.[0].rows).toEqual(firstRows);

    // A new message mounts only itself.
    messages = [said("m3", "Third.", "2026-10-17T10:02:00Z"), ...messages];
    rerender(<TaskConversation roomName="r" episode="urn:ep" onRows={onRows} />);
    expect(mounts).toEqual(["First.", "Second.", "Third."]);
    expect(onRows.mock.calls.at(-1)?.[0].rows).toEqual(["m1", "m2", "m3"]);
  });
});
