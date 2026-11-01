// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An ask: an agent asking a person for something the hub knows how to draw.
// Three kinds: `approve` (a yes or no on what the agent will do), `choose`
// (pick one option, or several) and `question` (an open question). Every kind
// takes a note with its answer. The agent fills in the fields, the app draws
// the card, and the answer goes back to the agent as values, never as prose it
// has to read (contracts/approvals.json).

import { keyProblem } from "@/lib/memory-location";

// Frozen in contracts/approvals.json; approvals.test.ts holds this copy to it.
export const PAYLOAD_KEYS = { ask: "ask", answer: "answer" } as const;
export const ASK_KINDS = ["approve", "choose", "question"] as const;
export const ASK_FIELDS = {
  required: ["id", "kind", "to", "question"],
  optional: ["why", "happens", "undo", "link", "options", "multiple", "recommend", "suggest"],
} as const;
export const DECISIONS = ["approved", "declined"] as const;
export const ANSWER_FIELDS = {
  required: ["ask", "kind", "question", "for", "by", "at"],
  optional: ["decision", "choices", "chosen", "text"],
} as const;
export const WAITING_KIND = "approve";

export type AskKind = (typeof ASK_KINDS)[number];
export type Decision = (typeof DECISIONS)[number];

export interface AskOption {
  id: string;
  label: string;
  detail: string | null;
}

/** How an ask was answered, once it has been. */
export interface AskAnswer {
  kind: AskKind;
  question: string;
  /** Whom the ask was put to. */
  for: string | null;
  /** Who answered: the person asked, or anyone else in the room. */
  by: string;
  at: string;
  decision: Decision | null;
  choices: string[];
  /** The labels of `choices`, as they read on the card. */
  chosen: string[];
  /** The note sent with any kind, and the whole answer to a question. */
  text: string | null;
}

export interface ApprovalAsk {
  id: string;
  kind: AskKind;
  /** The person it's put to. Anyone else in the room may answer it too. */
  to: string;
  question: string;
  happens: string | null;
  why: string | null;
  undo: string | null;
  link: string | null;
  /** A choose's options, numbered by the hub. */
  options: AskOption[];
  /** A choose that takes several options. */
  multiple: boolean;
  /** The options the agent recommends, on a choose. */
  recommend: string[];
  /** On an approve: the agent recommends saying yes. */
  recommendsApprove: boolean;
  /** On a question: the agent's draft answer. */
  suggest: string | null;
  /** Folded onto the ask by the hub once it's answered. */
  answer: AskAnswer | null;
}

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

function asAnswer(v: unknown, ask?: { kind: AskKind; question: string; to: string }): AskAnswer | null {
  if (!v || typeof v !== "object") return null;
  const a = v as Record<string, unknown>;
  const by = str(a.by);
  if (!by) return null;
  const decision = DECISIONS.find((d) => d === a.decision) ?? null;
  const choices = strs(a.choices);
  // A v1 answer carried no kind; a decision says it was an approve.
  const kind = ASK_KINDS.find((k) => k === a.kind) ?? ask?.kind ?? (decision ? "approve" : choices.length ? "choose" : "question");
  return {
    kind,
    question: str(a.question) ?? ask?.question ?? "",
    for: str(a.for) ?? ask?.to ?? null,
    by,
    at: str(a.at) ?? "",
    decision,
    choices,
    chosen: strs(a.chosen),
    // `reason` is what a v1 answer called its note.
    text: str(a.text) ?? str(a.reason),
  };
}

function asOptions(v: unknown): AskOption[] {
  if (!Array.isArray(v)) return [];
  return v.flatMap((o) => {
    const id = str((o as { id?: unknown })?.id);
    const label = str((o as { label?: unknown })?.label);
    return id && label ? [{ id, label, detail: str((o as { detail?: unknown }).detail) }] : [];
  });
}

function asAsk(v: unknown): ApprovalAsk | null {
  if (!v || typeof v !== "object") return null;
  const a = v as Record<string, unknown>;
  const id = str(a.id);
  const to = str(a.to);
  const question = str(a.question);
  const kind = ASK_KINDS.find((k) => k === a.kind);
  const options = asOptions(a.options);
  // A kind this app doesn't know, or a choose with nothing to pick, is drawn
  // as the plain message it also is.
  if (!kind || !id || !to || !question || (kind === "choose" && options.length < 2)) return null;
  return {
    id,
    kind,
    to,
    question,
    happens: str(a.happens),
    why: str(a.why),
    undo: str(a.undo),
    link: str(a.link),
    options,
    multiple: kind === "choose" && a.multiple === true,
    recommend: kind === "choose" ? strs(a.recommend) : [],
    recommendsApprove: kind === "approve" && a.recommend === "approve",
    suggest: kind === "question" ? str(a.suggest) : null,
    answer: asAnswer(a.answer, { kind, question, to }),
  };
}

function payloadData(content: unknown): Record<string, unknown> | null {
  if (typeof content === "string") {
    if (!content.startsWith("{")) return null;
    try {
      content = JSON.parse(content);
    } catch {
      return null;
    }
  }
  return (content as { l9?: { payload?: { data?: Record<string, unknown> } } } | null)?.l9?.payload?.data ?? null;
}

/** What an ask's `link` points at: a page on the web, one of the room's
 *  memories (a key with a folder, like `decisions/launch`), or neither, which
 *  is drawn as plain text. */
export function linkKind(link: string): "web" | "memory" | "text" {
  if (/^https?:\/\/\S+$/i.test(link)) return "web";
  if (link.includes("/") && keyProblem(link) === null) return "memory";
  return "text";
}

/** What an answer decided, in a few words: "Approved", "Declined", "Chose
 *  Stripe", or "Answered". */
export function verdictOf(answer: AskAnswer): string {
  if (answer.kind === "approve") return answer.decision === "declined" ? "Declined" : "Approved";
  if (answer.kind === "choose") return `Chose ${answer.chosen.length ? answer.chosen.join(", ") : answer.choices.join(", ")}`;
  return "Answered";
}

/** A person's answer, as the message that carries it back to the agent. */
export interface AskReply extends AskAnswer {
  ask: string;
}

/** The answer a message carries, when it's a person's answer to an ask. That
 *  message is how the agent hears it; in the feed, the ask's card says it. */
export function answerOf(message: { content?: unknown; metadata?: unknown }): AskReply | null {
  const raw =
    (message.metadata as Record<string, unknown> | null | undefined)?.[PAYLOAD_KEYS.answer] ??
    payloadData(message.content)?.[PAYLOAD_KEYS.answer];
  const answer = asAnswer(raw);
  const ask = (raw as { ask?: unknown } | null | undefined)?.ask;
  return answer && typeof ask === "string" && ask ? { ...answer, ask } : null;
}

/** Each answer in `events` folded onto the ask it answers, for a feed that
 *  holds both. A history read has done this already; a live frame hasn't. */
export function foldAnswers<T extends { ask: ApprovalAsk | null; answers: AskReply | null }>(events: T[]): T[] {
  const replies = new Map(events.flatMap((ev) => (ev.answers ? [[ev.answers.ask, ev.answers] as const] : [])));
  if (replies.size === 0) return events;
  return events.map((ev) => {
    const reply = ev.ask && !ev.ask.answer ? replies.get(ev.ask.id) : undefined;
    if (!reply || !ev.ask) return ev;
    const { ask: _id, ...answer } = reply;
    void _id;
    return { ...ev, ask: { ...ev.ask, answer } };
  });
}

/** The ask a message carries: in its metadata on a history read, or in its
 *  payload on a live frame, the way a conductor's line rides. */
export function askOf(message: { content?: unknown; metadata?: unknown }): ApprovalAsk | null {
  return (
    asAsk((message.metadata as Record<string, unknown> | null | undefined)?.[PAYLOAD_KEYS.ask]) ??
    asAsk(payloadData(message.content)?.[PAYLOAD_KEYS.ask])
  );
}
