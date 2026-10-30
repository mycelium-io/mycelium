// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  ANSWER_FIELDS,
  ASK_FIELDS,
  ASK_KINDS,
  DECISIONS,
  PAYLOAD_KEYS,
  WAITING_KIND,
  answerOf,
  askOf,
  foldAnswers,
  type ApprovalAsk,
  type AskReply,
} from "@/lib/approvals";
import { WAITING_KINDS } from "@/lib/board/people";

const CONTRACT = JSON.parse(
  readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../../../contracts/approvals.json"), "utf8"),
);

const ASK = { id: "7e21c0a4", kind: "approve", to: "operator", question: "Flip it Friday?" };

describe("contracts/approvals.json", () => {
  it("is what the app reads", () => {
    expect(PAYLOAD_KEYS).toEqual(CONTRACT.payload_keys);
    expect([...ASK_KINDS]).toEqual(CONTRACT.kinds);
    expect({ required: [...ASK_FIELDS.required], optional: [...ASK_FIELDS.optional] }).toEqual(CONTRACT.ask_fields);
    expect([...DECISIONS]).toEqual(CONTRACT.decisions);
    expect({ required: [...ANSWER_FIELDS.required], optional: [...ANSWER_FIELDS.optional] }).toEqual(
      CONTRACT.answer_fields,
    );
    expect(WAITING_KIND).toBe(CONTRACT.waiting_kind);
    expect(WAITING_KINDS).toContain(CONTRACT.waiting_kind);
  });

  it("draws an ask with every field the contract names", () => {
    const fields = [...CONTRACT.ask_fields.required, ...CONTRACT.ask_fields.optional] as string[];
    const full = Object.fromEntries(fields.map((f) => [f, f === "kind" ? "approve" : `the ${f}`]));
    const ask = askOf({ metadata: { ask: full } });
    for (const f of fields) expect(ask?.[f as keyof ApprovalAsk]).toBe(full[f]);
  });
});

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

describe("answerOf", () => {
  it("reads the answer a message carries, and which ask it answers", () => {
    const answer = { ask: "7e21c0a4", decision: "approved", by: "operator", at: "2026-10-30T10:42:00Z" };
    expect(answerOf({ metadata: { answer } })).toEqual({ ...answer, reason: null });
    expect(answerOf({ metadata: { conductor: {} } })).toBeNull();
  });
});

describe("foldAnswers", () => {
  const asked = { ask: askOf({ metadata: { ask: ASK } }), answers: null as AskReply | null };
  const reply: AskReply = { ask: "7e21c0a4", decision: "declined", reason: "Not yet", by: "operator", at: "now" };

  it("puts a live answer on the card of the ask it answers", () => {
    const [card] = foldAnswers([asked, { ask: null, answers: reply }]);
    expect(card.ask?.answer).toEqual({ decision: "declined", reason: "Not yet", by: "operator", at: "now" });
  });

  it("leaves an ask with no answer in the feed as it is", () => {
    const events = [asked];
    expect(foldAnswers(events)).toBe(events);
  });
});
