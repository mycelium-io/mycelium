// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it, vi } from "vitest";
import { renderWithSWR } from "@/test/swr";
import { KeymapProvider } from "@/components/keymap-provider";
import type { Event } from "@/lib/room-events";
import type { Interrupted } from "@/components/messages/mention-wakes";

/** Each time a message's row draws, its interrupt mark draws with what it was given. */
const drawn: (Interrupted[] | undefined)[] = [];
vi.mock("@/components/messages/mention-wakes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/messages/mention-wakes")>()),
  InterruptMark: ({ marks }: { marks?: Interrupted[] }) => {
    drawn.push(marks);
    return null;
  },
}));
vi.mock("@/components/current-user", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/current-user")>()),
  useCurrentUser: () => ({ principal: "julia" }),
}));

import { FeedRow, type FeedContext } from "./feed-row";

const message: Event = {
  id: "m1",
  messageId: "m1",
  wireId: null,
  type: "broadcast",
  content: "The totals match the receipts.",
  sender: "builder",
  recipient: null,
  time: "20:30:00",
  at: "2026-10-18T20:30:00.000Z",
  episode: null,
  amends: null,
  edited: false,
  reactions: [],
  reacts: null,
  thread: null,
  pingSenders: [],
  conductor: null,
  ask: null,
  answers: null,
  raw: {},
};

const ctx: FeedContext = {
  roomName: "checkout",
  agentHandles: new Set(["builder"]),
  engineHandles: new Set(),
  agentTags: new Map(),
  agentOwners: new Map(),
  threads: new Map(),
  rowNames: new Map(),
  flagsByMessage: new Map(),
  refreshFlags: () => {},
};

function rows(props: Partial<React.ComponentProps<typeof FeedRow>> = {}) {
  return (
    <KeymapProvider>
      <FeedRow ev={message} ctx={ctx} {...props} />
    </KeymapProvider>
  );
}

describe("a message's row in a list that draws again", () => {
  it("doesn't draw again when nothing it shows changed", () => {
    drawn.length = 0;
    const query = ["refund"];
    const { rerender } = renderWithSWR(rows({ hit: { query, active: false } }));
    expect(drawn).toHaveLength(1);
    // A find passes a new hit each time it draws, holding the same.
    rerender(rows({ hit: { query, active: false } }));
    rerender(rows({ hit: { query, active: false } }));
    expect(drawn).toHaveLength(1);
  });

  it("draws again when its message's interrupts change", () => {
    drawn.length = 0;
    const { rerender } = renderWithSWR(rows());
    const marks: Interrupted[] = [{ by: "builder", handle: "scout", at: "2026-10-18T20:30:00.000Z" }];
    rerender(rows({ interrupted: marks }));
    expect(drawn.at(-1)).toBe(marks);
    expect(drawn).toHaveLength(2);
  });

  it("draws again when the room's context changes", () => {
    drawn.length = 0;
    const { rerender } = renderWithSWR(rows());
    rerender(rows({ ctx: { ...ctx, agentHandles: new Set() } }));
    expect(drawn).toHaveLength(2);
  });
});
