// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { answersAsk, askOf } from "@/lib/approvals";

const ASK = { id: "7e21c0a4", kind: "approve", to: "operator", question: "Flip it Friday?" };

describe("askOf", () => {
  it("reads an ask from a history read's metadata", () => {
    const ask = askOf({ content: "Flip it Friday?", metadata: { ask: { ...ASK, undo: "Turn it off." } } });
    expect(ask).toMatchObject({ id: "7e21c0a4", to: "operator", question: "Flip it Friday?", undo: "Turn it off.", happens: null });
    expect(ask?.answer).toBeNull();
  });

  it("reads one from a live frame's payload", () => {
    const content = JSON.stringify({ l9: { payload: { data: { ask: ASK } } } });
    expect(askOf({ content, metadata: null })?.id).toBe("7e21c0a4");
  });

  it("reads the answer the hub folded onto it", () => {
    const answer = { decision: "declined", reason: "Not yet", by: "operator", at: "2026-10-30T10:42:00Z" };
    expect(askOf({ metadata: { ask: { ...ASK, answer } } })?.answer).toEqual(answer);
  });

  it("leaves a kind it doesn't know, or a broken ask, as a plain message", () => {
    expect(askOf({ metadata: { ask: { ...ASK, kind: "choose" } } })).toBeNull();
    expect(askOf({ metadata: { ask: { ...ASK, question: "" } } })).toBeNull();
    expect(askOf({ metadata: null })).toBeNull();
  });
});

describe("answersAsk", () => {
  it("names the ask an answer is to", () => {
    expect(answersAsk({ metadata: { answer: { ask: "7e21c0a4", decision: "approved" } } })).toBe("7e21c0a4");
    expect(answersAsk({ metadata: { conductor: {} } })).toBeNull();
  });
});
