// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { matchLanded, type Landed, type PendingMessage } from "@/lib/pending-messages";

const NOW = Date.parse("2026-10-08T12:00:00Z");

function pending(over: Partial<PendingMessage> = {}): PendingMessage {
  return {
    id: "p1",
    room: "atlas",
    episode: null,
    sender: "julia",
    content: "ship it",
    at: NOW,
    state: "sending",
    error: null,
    messageId: null,
    ...over,
  };
}

function landed(over: Partial<Landed> = {}): Landed {
  return { id: "m1", sender: "julia", content: "ship it", at: "2026-10-08T12:00:01Z", ...over };
}

describe("matchLanded", () => {
  it("matches by the id the hub returned", () => {
    const sent = pending({ state: "sent", messageId: "m9", content: "ship it" });
    expect(matchLanded([sent], [landed({ id: "m9", content: "different text" })])).toEqual(new Set(["p1"]));
  });

  it("matches a copy from the stream by sender and text", () => {
    expect(matchLanded([pending()], [landed({ id: "envelope-id" })])).toEqual(new Set(["p1"]));
  });

  it("does not take an older message with the same words for the one just sent", () => {
    expect(matchLanded([pending()], [landed({ at: "2026-10-08T11:50:00Z" })]).size).toBe(0);
  });

  it("does not match someone else saying the same thing", () => {
    expect(matchLanded([pending()], [landed({ sender: "risk" })]).size).toBe(0);
  });

  it("lets one read message stand for one pending message", () => {
    const twice = [pending({ id: "p1" }), pending({ id: "p2" })];
    expect(matchLanded(twice, [landed()])).toEqual(new Set(["p1"]));
  });

  it("never matches a failed send, which stays until it is retried or let go", () => {
    expect(matchLanded([pending({ state: "failed" })], [landed()]).size).toBe(0);
  });
});
