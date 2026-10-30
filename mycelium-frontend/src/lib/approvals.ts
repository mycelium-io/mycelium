// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An ask: an agent asking one person for something the hub knows how to draw.
// v1 has one kind, `approve`. The agent fills in the fields, the app draws the
// card, and the person's answer goes back to the agent as values, never as
// prose it has to read (contracts/approvals.json).

/** How an ask was answered, once it has been. */
export interface AskAnswer {
  decision: "approved" | "declined";
  reason: string | null;
  by: string;
  at: string;
}

export interface ApprovalAsk {
  id: string;
  kind: "approve";
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
  if (a.decision !== "approved" && a.decision !== "declined") return null;
  const by = str(a.by);
  if (!by) return null;
  return { decision: a.decision, reason: str(a.reason), by, at: str(a.at) ?? "" };
}

function asAsk(v: unknown): ApprovalAsk | null {
  if (!v || typeof v !== "object") return null;
  const a = v as Record<string, unknown>;
  const id = str(a.id);
  const to = str(a.to);
  const question = str(a.question);
  // A kind this app doesn't know is drawn as the plain message it also is.
  if (a.kind !== "approve" || !id || !to || !question) return null;
  return {
    id,
    kind: "approve",
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

/** The ask a message answers, when it's a person's answer to one. That message
 *  is how the agent hears it; in the feed, the ask's card already says it. */
export function answersAsk(message: { content?: unknown; metadata?: unknown }): string | null {
  const answer =
    (message.metadata as { answer?: unknown } | null | undefined)?.answer ?? payloadData(message.content)?.answer;
  const ask = (answer as { ask?: unknown } | null | undefined)?.ask;
  return typeof ask === "string" && ask ? ask : null;
}

/** The ask a message carries: in its metadata on a history read, or in its
 *  payload on a live frame, the way a conductor's line rides. */
export function askOf(message: { content?: unknown; metadata?: unknown }): ApprovalAsk | null {
  return (
    asAsk((message.metadata as { ask?: unknown } | null | undefined)?.ask) ??
    asAsk(payloadData(message.content)?.ask)
  );
}
