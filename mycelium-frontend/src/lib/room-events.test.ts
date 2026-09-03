// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it, vi } from "vitest";
import { parseEvent, unwrapContent } from "@/lib/room-events";
import { NOTICE_TYPE, PING_TYPE } from "@/lib/threads";

const CREATED = "2026-08-04T10:00:00.000000+00:00";

describe("unwrapContent", () => {
  it("wraps a chat message's plain string as {text} instead of parsing it", () => {
    expect(unwrapContent({ message_type: "broadcast", content: "hello room" })).toEqual({
      text: "hello room",
    });
  });

  it("parses a coordination event's JSON blob", () => {
    expect(
      unwrapContent({ message_type: "coordination_join", content: '{"handle":"growth"}' }),
    ).toEqual({ handle: "growth" });
  });

  it("passes an object content through", () => {
    const content = { round: 2 };
    expect(unwrapContent({ message_type: "coordination_tick", content })).toBe(content);
  });

  it("treats the message itself as the payload when there is no content", () => {
    // Route-level events carry their fields flat on the message.
    const msg = { message_type: "memory_changed", key: "decisions/scope", version: 3 };
    expect(unwrapContent(msg)).toBe(msg);
  });

  it("falls back rather than throwing on a malformed blob", () => {
    const msg = { message_type: "l9_exchange", content: "{not json" };
    expect(unwrapContent(msg)).toBe(msg);
  });

  it("keeps the raw string on a chat type even when it looks like JSON", () => {
    expect(unwrapContent({ message_type: "direct", content: '{"a":1}' })).toEqual({
      text: '{"a":1}',
    });
  });
});

describe("parseEvent", () => {
  it("reads a chat message straight through", () => {
    const ev = parseEvent({
      id: "m1",
      message_type: "direct",
      sender_handle: "growth",
      recipient_handle: "risk",
      content: "cut over tonight?",
      created_at: CREATED,
    });
    expect(ev).toMatchObject({
      messageId: "m1",
      type: "direct",
      content: "cut over tonight?",
      sender: "growth",
      recipient: "risk",
      time: CREATED.slice(11, 19),
      at: CREATED,
      episode: null,
      amends: null,
      edited: false,
      thread: null,
      pingSenders: [],
    });
  });

  it("reads a tick's fields out of the nested payload", () => {
    const ev = parseEvent({
      message_type: "coordination_tick",
      sender_handle: "aligner",
      content: JSON.stringify({
        payload: { round: 4, participant_id: "risk", action: "accept", current_offer: { window: "night" } },
      }),
      created_at: CREATED,
    });
    expect(ev.type).toBe("coordination_tick");
    expect(ev.content).toBe('Round 4: risk → accept {"window":"night"}');
  });

  it("renders a join with its intent", () => {
    const ev = parseEvent({
      message_type: "coordination_join",
      sender_handle: "growth",
      content: JSON.stringify({ handle: "growth", intent: "argue for the phased cutover" }),
      created_at: CREATED,
    });
    expect(ev.content).toBe("growth joined: argue for the phased cutover");
  });

  it("summarizes a consensus with assignments, compiled rows and GAR", () => {
    const ev = parseEvent({
      message_type: "coordination_consensus",
      sender_handle: "aligner",
      content: JSON.stringify({
        assignments: { cutover: "phased", owner: "growth" },
        tasks: ["t1", "t2"],
        metrics: { gar: 1 },
      }),
      created_at: CREATED,
    });
    expect(ev.content).toBe("cutover=phased, owner=growth · compiled → 2 rows · GAR 1.00");
  });

  it("reads memory_changed fields from the message itself when there is no content", () => {
    const ev = parseEvent({
      message_type: "memory_changed",
      key: "decisions/scope",
      version: 3,
      updated_by: "aligner",
      created_at: CREATED,
    });
    expect(ev.content).toBe("decisions/scope v3 by aligner");
  });

  it("unwraps a live l9_exchange back into the chat shape a refresh would show", () => {
    const ev = parseEvent({
      message_type: "l9_exchange",
      sender_handle: "growth",
      content: JSON.stringify({ content: "dual-write is live" }),
      created_at: CREATED,
    });
    expect(ev.type).toBe("broadcast");
    expect(ev.content).toBe("dual-write is live");
  });

  it("names a ping for its thread and writer, not the system that raised it", () => {
    const ev = parseEvent({
      message_type: "l9_exchange",
      sender_handle: "system",
      content: JSON.stringify({
        l9: { payload: { type: "ping", data: { episode: "urn:ioc:mycelium:episode:atlas:abc123", sender: "growth", message: "m9" } } },
      }),
      created_at: CREATED,
    });
    expect(ev.type).toBe(PING_TYPE);
    expect(ev.thread).toBe("urn:ioc:mycelium:episode:atlas:abc123");
    expect(ev.pingSenders).toEqual(["growth"]);
  });

  it("reads a board notice as a notice, with the task's thread to open", () => {
    const ev = parseEvent({
      message_type: "l9_exchange",
      sender_handle: "system",
      content: JSON.stringify({
        l9: {
          payload: {
            type: "notice",
            data: {
              key: "work/cache-sweep",
              subkind: "resolved",
              title: "cache sweep",
              episode: "urn:ioc:mycelium:episode:atlas:t1",
              by: "growth",
            },
          },
        },
      }),
      created_at: CREATED,
    });
    expect(ev.type).toBe(NOTICE_TYPE);
    expect(ev.content).toBe("cache sweep");
    expect(ev.thread).toBe("urn:ioc:mycelium:episode:atlas:t1");
    expect(ev.raw.taskKey).toBe("work/cache-sweep");
    expect(ev.raw.by).toBe("growth");
  });

  it("normalizes an l9_commit into the coordination_consensus shape", () => {
    const ev = parseEvent({
      message_type: "l9_commit",
      sender_handle: "aligner",
      content: JSON.stringify({
        l9: {
          header: { subkind: "converged", message: { episode: "urn:e:s1" } },
          payload: { data: { assignments: { scope: "mvp" }, metrics: { gar: 0.5 } } },
        },
      }),
      created_at: CREATED,
    });
    expect(ev.type).toBe("coordination_consensus");
    expect(ev.raw.broken).toBe(false);
    expect(ev.raw.assignments).toEqual({ scope: "mvp" });
    expect(ev.raw.metrics).toEqual({ gar: 0.5 });
    expect(ev.raw.episode).toBe("urn:e:s1");
  });

  it("marks a non-converged commit as broken", () => {
    const ev = parseEvent({
      message_type: "l9_commit",
      sender_handle: "aligner",
      content: JSON.stringify({ l9: { header: { subkind: "rejected" } } }),
      created_at: CREATED,
    });
    expect(ev.raw.broken).toBe(true);
  });

  it("reads an l9_knowledge push as its own notice with the memory fields kept", () => {
    const ev = parseEvent({
      message_type: "l9_knowledge",
      sender_handle: "synthesizer",
      content: JSON.stringify({
        l9: { payload: { data: { key: "context/synthesis", updated_by: "synthesizer", version: 2 } } },
      }),
      created_at: CREATED,
    });
    expect(ev.type).toBe("l9_knowledge");
    expect(ev.content).toBe("context/synthesis updated");
    expect(ev.raw.key).toBe("context/synthesis");
    expect(ev.raw.version).toBe(2);
  });

  it("reads the episode off the message or the envelope header", () => {
    expect(
      parseEvent({ message_type: "broadcast", sender_handle: "a", content: "hi", episode: "urn:e:1" }).episode,
    ).toBe("urn:e:1");
    expect(
      parseEvent({
        message_type: "l9_exchange",
        sender_handle: "a",
        content: JSON.stringify({ content: "hi", header: { message: { episode: "urn:e:2" } } }),
      }).episode,
    ).toBe("urn:e:2");
    expect(parseEvent({ message_type: "broadcast", sender_handle: "a", content: "hi" }).episode).toBeNull();
  });

  it("reads an amendment's target off the L9 header, and a folded edit off edited_at", () => {
    const amendment = parseEvent({
      message_type: "l9_exchange",
      sender_handle: "growth",
      content: JSON.stringify({
        content: "actually, Friday",
        l9: { header: { subkind: "amend", message: { parents: ["m42"] } } },
      }),
      created_at: CREATED,
    });
    expect(amendment.amends).toBe("m42");

    const folded = parseEvent({
      message_type: "broadcast",
      sender_handle: "growth",
      content: "actually, Friday",
      edited_at: CREATED,
    });
    expect(folded.amends).toBeNull();
    expect(folded.edited).toBe(true);
  });

  it("warns loudly on an unhandled type rather than dropping it silently", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      const ev = parseEvent({
        message_type: "a_future_type",
        sender_handle: "growth",
        content: "the future",
        created_at: CREATED,
      });
      expect(ev.content).toBe("the future");
      expect(warn).toHaveBeenCalledOnce();
      expect(warn.mock.calls[0][0]).toContain("a_future_type");
    } finally {
      warn.mockRestore();
    }
  });
});
