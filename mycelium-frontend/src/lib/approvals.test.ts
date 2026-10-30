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
  verdictOf,
  type AskReply,
} from "@/lib/approvals";
import { WAITING_KINDS } from "@/lib/board/people";

const CONTRACT = JSON.parse(
  readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../../../contracts/approvals.json"), "utf8"),
);

const ASK = { id: "7e21c0a4", kind: "approve", to: "operator", question: "Flip it Friday?" };
const CHOOSE = {
  id: "3f9c1a2b",
  kind: "choose",
  to: "operator",
  question: "Which payment provider first?",
  options: [
    { id: "1", label: "Stripe" },
    { id: "2", label: "Adyen", detail: "Needs a new contract." },
  ],
  recommend: ["1"],
};

describe("contracts/approvals.json", () => {
  it("is what the app reads", () => {
    expect(PAYLOAD_KEYS).toEqual(CONTRACT.payload_keys);
    expect([...ASK_KINDS]).toEqual(CONTRACT.kinds);
    expect([...ASK_FIELDS.required]).toEqual(CONTRACT.ask_fields.required);
    // Optional on an ask: the facts any kind may carry, and what each kind adds.
    const byKind = Object.values(CONTRACT.ask_fields.kind_fields as Record<string, string[]>).flat();
    expect(new Set(ASK_FIELDS.optional)).toEqual(new Set([...CONTRACT.ask_fields.facts, ...byKind]));
    expect([...DECISIONS]).toEqual(CONTRACT.decisions);
    expect({ required: [...ANSWER_FIELDS.required], optional: [...ANSWER_FIELDS.optional] }).toEqual(
      CONTRACT.answer_fields,
    );
    expect(WAITING_KIND).toBe(CONTRACT.waiting_kind);
    expect(WAITING_KINDS).toContain(CONTRACT.waiting_kind);
  });
});

describe("askOf", () => {
  it("reads an approve from a history read's metadata", () => {
    const ask = askOf({ content: "Flip it Friday?", metadata: { ask: { ...ASK, undo: "Turn it off.", recommend: "approve" } } });
    expect(ask).toMatchObject({ id: "7e21c0a4", kind: "approve", undo: "Turn it off.", happens: null, recommendsApprove: true });
    expect(ask?.answer).toBeNull();
  });

  it("reads one from a live frame's payload", () => {
    const content = JSON.stringify({ l9: { payload: { data: { ask: ASK } } } });
    expect(askOf({ content, metadata: null })?.id).toBe("7e21c0a4");
  });

  it("reads a choose's options and the agent's picks", () => {
    const ask = askOf({ metadata: { ask: { ...CHOOSE, multiple: true } } });
    expect(ask?.options).toEqual([
      { id: "1", label: "Stripe", detail: null },
      { id: "2", label: "Adyen", detail: "Needs a new contract." },
    ]);
    expect(ask?.multiple).toBe(true);
    expect(ask?.recommend).toEqual(["1"]);
  });

  it("reads a question's draft answer", () => {
    expect(askOf({ metadata: { ask: { ...ASK, kind: "question", suggest: "The address form." } } })?.suggest).toBe("The address form.");
  });

  it("reads the answer the hub folded onto it, naming its question", () => {
    const answer = { kind: "choose", question: "Which payment provider first?", for: "operator", by: "jamie", at: "t", choices: ["1"], chosen: ["Stripe"], text: "later" };
    expect(askOf({ metadata: { ask: { ...CHOOSE, answer } } })?.answer).toEqual({ ...answer, decision: null });
  });

  it("reads a v1 answer, whose note was its reason", () => {
    const answer = { decision: "declined", reason: "Not yet", by: "operator", at: "t" };
    expect(askOf({ metadata: { ask: { ...ASK, answer } } })?.answer).toMatchObject({
      kind: "approve",
      question: "Flip it Friday?",
      for: "operator",
      decision: "declined",
      text: "Not yet",
    });
  });

  it("leaves a kind it doesn't know, a choose with nothing to pick, or a broken ask, as a plain message", () => {
    expect(askOf({ metadata: { ask: { ...ASK, kind: "rank" } } })).toBeNull();
    expect(askOf({ metadata: { ask: { ...CHOOSE, options: [{ id: "1", label: "Only one" }] } } })).toBeNull();
    expect(askOf({ metadata: { ask: { ...ASK, question: "" } } })).toBeNull();
    expect(askOf({ metadata: null })).toBeNull();
  });
});

describe("verdictOf", () => {
  const base = { question: "q", for: "operator", by: "operator", at: "", choices: [], chosen: [], text: null };
  it("says what was decided", () => {
    expect(verdictOf({ ...base, kind: "approve", decision: "approved" })).toBe("Approved");
    expect(verdictOf({ ...base, kind: "approve", decision: "declined" })).toBe("Declined");
    expect(verdictOf({ ...base, kind: "choose", decision: null, choices: ["1", "3"], chosen: ["A", "C"] })).toBe("Chose A, C");
    expect(verdictOf({ ...base, kind: "question", decision: null, text: "x" })).toBe("Answered");
  });
});

describe("answerOf", () => {
  it("reads the answer a message carries, and which ask it answers", () => {
    const answer = { ask: "7e21c0a4", kind: "approve", question: "Flip it Friday?", for: "operator", decision: "approved", by: "jamie", at: "t" };
    expect(answerOf({ metadata: { answer } })).toEqual({ ...answer, choices: [], chosen: [], text: null });
    expect(answerOf({ metadata: { conductor: {} } })).toBeNull();
  });
});

describe("foldAnswers", () => {
  const asked = { ask: askOf({ metadata: { ask: ASK } }), answers: null as AskReply | null };
  const reply: AskReply = {
    ask: "7e21c0a4",
    kind: "approve",
    question: "Flip it Friday?",
    for: "operator",
    by: "operator",
    at: "now",
    decision: "declined",
    choices: [],
    chosen: [],
    text: "Not yet",
  };

  it("puts a live answer on the card of the ask it answers", () => {
    const [card] = foldAnswers([asked, { ask: null, answers: reply }]);
    expect(card.ask?.answer).toMatchObject({ decision: "declined", text: "Not yet", by: "operator" });
  });

  it("leaves an ask with no answer in the feed as it is", () => {
    const events = [asked];
    expect(foldAnswers(events)).toBe(events);
  });
});
