// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { classify, DEFAULT_SETTINGS, isAdmitted, isAlert, roomLevel } from "@/lib/notifications";

const CREATED = "2026-08-15T10:00:00.000000+00:00";

function l9Exchange(text: string, opts: Partial<Record<string, unknown>> = {}) {
  return {
    id: "msg-1",
    room_name: "sprint",
    sender_handle: "alice",
    message_type: "l9_exchange",
    created_at: CREATED,
    content: JSON.stringify({ content: text }),
    ...opts,
  };
}

describe("classify", () => {
  it("recognizes an @-mention addressed to the acting principal", () => {
    const n = classify(l9Exchange("hey @bob can you take a look?"), "bob");
    expect(n).toMatchObject({ room: "sprint", kind: "mention", needsMe: true });
  });

  it("classifies a message that doesn't mention you as ambient (badge-only)", () => {
    const n = classify(l9Exchange("hey @carol can you take a look?"), "bob");
    expect(n).toMatchObject({ kind: "message", needsMe: false });
  });

  it("ignores your own post", () => {
    const n = classify(l9Exchange("just thinking out loud"), "alice");
    expect(n).toBeNull();
  });

  it("recognizes a direct message by recipient handle, case-insensitively", () => {
    const n = classify(l9Exchange("here's the plan", { recipient_handle: "Bob" }), "bob");
    expect(n).toMatchObject({ kind: "direct", needsMe: true });
  });

  it("classifies a converged l9_commit as a needs-me consensus notification", () => {
    const raw = {
      room_name: "sprint",
      sender_handle: "aligner",
      message_type: "l9_commit",
      created_at: CREATED,
      content: JSON.stringify({
        content: "consensus reached",
        l9: { header: { subkind: "converged" } },
      }),
    };
    const n = classify(raw, "bob");
    expect(n).toMatchObject({ kind: "consensus", needsMe: true, summary: "consensus reached" });
  });

  it("classifies l9_knowledge as a needs-me knowledge notification", () => {
    const raw = {
      room_name: "sprint",
      sender_handle: "system",
      message_type: "l9_knowledge",
      created_at: CREATED,
      content: JSON.stringify({ content: "plan updated → plan/tasks.md" }),
    };
    const n = classify(raw, "bob");
    expect(n).toMatchObject({ kind: "knowledge", needsMe: true });
  });

  it("classifies a coordination_join as ambient (not needs-me)", () => {
    const raw = {
      room_name: "sprint",
      sender_handle: "system",
      message_type: "coordination_join",
      created_at: CREATED,
      content: JSON.stringify({ handle: "carol" }),
    };
    const n = classify(raw, "bob");
    expect(n).toMatchObject({ kind: "join", needsMe: false, summary: "carol joined" });
  });

  it("returns null for a frame with no room_name (global app events)", () => {
    const n = classify({ type: "room_created", room_name: undefined }, "bob");
    expect(n).toBeNull();
  });

  it("returns null for an unrecognized message_type", () => {
    const n = classify(
      { room_name: "sprint", message_type: "memory_changed", content: "{}" },
      "bob",
    );
    expect(n).toBeNull();
  });
});

describe("isAdmitted", () => {
  const mention = classify(l9Exchange("hey @bob"), "bob")!;
  const join = classify(
    {
      room_name: "sprint",
      sender_handle: "system",
      message_type: "coordination_join",
      created_at: CREATED,
      content: JSON.stringify({ handle: "carol" }),
    },
    "bob",
  )!;

  it("admits a needs-me item under the default (needs-me) scope", () => {
    expect(isAdmitted(mention, DEFAULT_SETTINGS)).toBe(true);
  });

  it("rejects an ambient item under needs-me scope", () => {
    expect(isAdmitted(join, DEFAULT_SETTINGS)).toBe(false);
  });

  it("admits an ambient item under everything scope", () => {
    expect(isAdmitted(join, { ...DEFAULT_SETTINGS, scope: "everything" })).toBe(true);
  });

  it("rejects everything under global do-not-disturb", () => {
    expect(isAdmitted(mention, { ...DEFAULT_SETTINGS, dnd: true })).toBe(false);
  });

  it("rejects a notification from a muted room", () => {
    expect(isAdmitted(mention, { ...DEFAULT_SETTINGS, mutedRooms: ["sprint"] })).toBe(false);
  });
});

describe("roomLevel", () => {
  it("defaults to mentions under needs-me scope, all under everything", () => {
    expect(roomLevel(DEFAULT_SETTINGS, "sprint")).toBe("mentions");
    expect(roomLevel({ ...DEFAULT_SETTINGS, scope: "everything" }, "sprint")).toBe("all");
  });

  it("lets a per-room override win over the scope default and legacy mute", () => {
    const s = { ...DEFAULT_SETTINGS, mutedRooms: ["sprint"], roomLevels: { sprint: "all" as const } };
    expect(roomLevel(s, "sprint")).toBe("all");
  });

  it("reads a legacy muted room as muted", () => {
    expect(roomLevel({ ...DEFAULT_SETTINGS, mutedRooms: ["sprint"] }, "sprint")).toBe("muted");
  });
});

describe("isAlert", () => {
  const mention = classify(l9Exchange("hey @bob"), "bob")!;
  const message = classify(l9Exchange("morning all"), "bob")!;

  it("is loud for a mention under the default (mentions) level", () => {
    expect(isAlert(mention, DEFAULT_SETTINGS)).toBe(true);
  });

  it("is quiet (badge-only) for ambient chatter under mentions", () => {
    expect(isAlert(message, DEFAULT_SETTINGS)).toBe(false);
  });

  it("is loud for ambient chatter when the room is on all", () => {
    const s = { ...DEFAULT_SETTINGS, roomLevels: { sprint: "all" as const } };
    expect(isAlert(message, s)).toBe(true);
  });

  it("is silent for anything in a muted room", () => {
    const s = { ...DEFAULT_SETTINGS, roomLevels: { sprint: "muted" as const } };
    expect(isAlert(mention, s)).toBe(false);
  });
});
