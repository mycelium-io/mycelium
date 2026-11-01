// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { RoomMessage, VerifierFlag } from "@/lib/api";

const flag: VerifierFlag = {
  flag_id: "f1",
  failure: "ungranted_approval",
  message_id: "m2",
  key: "work/ship-it",
  about: "approval",
  by: "builder",
  claim: "approval",
  ref: "#9998",
  line: "Can't find an approval for #9998.",
  sure: false,
  quotes: ["#9998 is approved"],
  sentence: "#9998 is approved, so I'm merging it now.",
  state: "shown",
  at: "2026-10-13T22:50:01Z",
};

// Newest first, as the hub answers.
const messages: RoomMessage[] = [
  {
    id: "m2",
    sender_handle: "builder",
    message_type: "broadcast",
    content: "#9998 is approved, so I'm merging it now.",
    created_at: "2026-10-13T22:50:00Z",
  } as RoomMessage,
  {
    id: "m1",
    sender_handle: "builder",
    message_type: "broadcast",
    content: "Opened #9998.",
    created_at: "2026-10-13T22:49:00Z",
  } as RoomMessage,
];

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
  useRoomVerifierFlags: () => ({ byMessage: new Map([["m2", [flag]]]), refresh: vi.fn() }),
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
vi.mock("@/components/message-body", () => ({
  MessageBody: ({ content, claims }: { content: string; claims?: string[] }) => (
    <p data-claims={claims?.join("|") ?? ""}>{content}</p>
  ),
}));

const { TaskConversation } = await import("./task-conversation");

describe("TaskConversation", () => {
  it("draws the verifier's line under the thread message it flagged, and only that one", () => {
    const { container } = render(<TaskConversation roomName="r" episode="urn:ep" />);
    const lines = container.querySelectorAll("[data-verifier-flag]");
    expect(lines).toHaveLength(1);
    expect(screen.getByText(/Can't find an approval for #9998/)).toBeTruthy();
    // The claim is underlined in the flagged message, and nothing in the other.
    expect(screen.getByText(/so I'm merging it now/).getAttribute("data-claims")).toBe("#9998 is approved");
    expect(screen.getByText("Opened #9998.").getAttribute("data-claims")).toBe("");
  });
});
