// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An ask: an agent asking one person for something the hub knows how to draw.
// v1 has one kind, `approve`. The agent fills in the fields, the app draws the
// card, and the person's answer goes back to the agent as values, never as
// prose it has to read (contracts/approvals.json).

import { keyProblem } from "@/lib/memory-location";

// Frozen in contracts/approvals.json; approvals.test.ts holds this copy to it.
export const PAYLOAD_KEYS = { ask: "ask", answer: "answer" } as const;
export const ASK_KINDS = ["approve"] as const;
export const ASK_FIELDS = {
  required: ["id", "kind", "to", "question"],
  optional: ["happens", "why", "undo", "link"],
} as const;
export const DECISIONS = ["approved", "declined"] as const;
export const ANSWER_FIELDS = { required: ["ask", "decision", "by", "at"], optional: ["reason"] } as const;
export const WAITING_KIND = "approve";

/** How an ask was answered, once it has been. */
export interface AskAnswer {
  decision: (typeof DECISIONS)[number];
  reason: string | null;
  by: string;
  at: string;
}

export interface ApprovalAsk {
  id: string;
  kind: (typeof ASK_KINDS)[number];
  /** The one person who can answer it. */
  to: string;
  question: string;
  happens: string | null;
  why: string | null;
  undo: string | null;
  link: string | null;
  /** Folded onto the ask by the hub once it's answered. */
  answer: AskAnswer | null;
}

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);

function asAnswer(v: unknown): AskAnswer | null {
  if (!v || typeof v !== "object") return null;
  const a = v as Record<string, unknown>;
  const decision = DECISIONS.find((d) => d === a.decision);
  const by = str(a.by);
  if (!decision || !by) return null;
  return { decision, reason: str(a.reason), by, at: str(a.at) ?? "" };
}

function asAsk(v: unknown): ApprovalAsk | null {
  if (!v || typeof v !== "object") return null;
  const a = v as Record<string, unknown>;
  const id = str(a.id);
  const to = str(a.to);
  const question = str(a.question);
  const kind = ASK_KINDS.find((k) => k === a.kind);
  // A kind this app doesn't know is drawn as the plain message it also is.
  if (!kind || !id || !to || !question) return null;
  return {
    id,
    kind,
    to,
    question,
    happens: str(a.happens),
    why: str(a.why),
    undo: str(a.undo),
    link: str(a.link),
    answer: asAnswer(a.answer),
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
    const answer = { decision: reply.decision, reason: reply.reason, by: reply.by, at: reply.at };
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
