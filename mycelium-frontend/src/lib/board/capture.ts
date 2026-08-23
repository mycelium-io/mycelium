// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Natural-language capture: one line in, a typed row out.
 *
 * Capture is the human's only authoring gesture on this surface — everything
 * else self-populates — so it parses the sigils people already type in chat
 * rather than asking for a form.
 */

import type { LiveItem } from "./item";

export interface ParsedCapture {
  title: string;
  fields: Record<string, unknown>;
  /** What the parser recognised, echoed under the input as you type. */
  hints: { label: string; value: string }[];
}

const PRIORITY_WORDS: Record<string, string> = {
  "!": "high",
  "!!": "urgent",
  "!!!": "urgent",
  urgent: "urgent",
  asap: "urgent",
  blocker: "urgent",
  soon: "high",
  nit: "low",
  someday: "low",
};

export function parseCapture(input: string, actor: string, now: string): ParsedCapture {
  const fields: Record<string, unknown> = {
    status: "open",
    kind: "concern",
    owner: null,
    priority: "normal",
    created: now,
    updated: now,
    // Captured rows are transient by default: a concern nobody claims expires
    // rather than settling into a backlog.
    ttl_minutes: 2880,
    captured_by: `@${actor}`,
  };
  const hints: { label: string; value: string }[] = [];
  const tags: string[] = [];

  let title = input;

  const owner = input.match(/(?:^|\s)@([a-z0-9][a-z0-9._-]*)/i);
  if (owner) {
    fields.owner = `@${owner[1]}`;
    fields.status = "claimed";
    fields.kind = "action";
    hints.push({ label: "owner", value: `@${owner[1]}` });
    title = title.replace(owner[0], " ");
  }

  const bang = input.match(/(?:^|\s)(!{1,3})(?=\s|$)/);
  if (bang) {
    fields.priority = PRIORITY_WORDS[bang[1]] ?? "high";
    hints.push({ label: "priority", value: String(fields.priority) });
    title = title.replace(bang[0], " ");
  } else {
    for (const [word, level] of Object.entries(PRIORITY_WORDS)) {
      if (/^[a-z]+$/.test(word) && new RegExp(`\\b${word}\\b`, "i").test(input)) {
        fields.priority = level;
        hints.push({ label: "priority", value: level });
        break;
      }
    }
  }

  for (const tag of input.matchAll(/(?:^|\s)#([a-z][a-z0-9._-]*)/gi)) {
    tags.push(tag[1]);
    title = title.replace(tag[0], " ");
  }
  if (tags.length) {
    fields.tags = tags;
    hints.push({ label: "tags", value: tags.join(", ") });
  }

  const issue = input.match(/(?:^|\s)(#\d+)(?=\s|$)/);
  if (issue) {
    fields.issue = issue[1];
    fields.blocked_by = [issue[1]];
    fields.status = "blocked";
    hints.push({ label: "blocked by", value: issue[1] });
    title = title.replace(issue[0], " ");
  }

  // A question is a decision to route, not a task to do.
  if (/\?\s*$/.test(input.trim())) {
    fields.kind = "decision";
    fields.status = "open";
    hints.push({ label: "kind", value: "decision" });
  }

  return { title: title.replace(/\s{2,}/g, " ").trim(), fields, hints };
}

/**
 * Where a captured row is filed, and under what key.
 *
 * A question routes to `decisions/` and everything else to `work/` — both are
 * live namespaces, so either way the row comes back through the projection.
 * The slug is the title, and the stamp on the end is what keeps two people
 * capturing "flaky test" a minute apart from overwriting each other: a memory
 * key is an identity, and two different concerns are not the same thing.
 */
export function captureKey(parsed: ParsedCapture, now: string): string {
  const namespace = parsed.fields.kind === "decision" ? "decisions" : "work";
  const slug =
    parsed.title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48) || "captured";
  // Seconds are enough: the collision this guards is two hands, not a loop.
  const stamp = now.replace(/[^0-9]/g, "").slice(4, 12);
  return `${namespace}/${slug}-${stamp}`;
}

export function captureToItem(parsed: ParsedCapture, seq: number, actor: string): LiveItem {
  return {
    id: `capture:${seq}`,
    title: parsed.title,
    source: { kind: "capture", label: `captured by @${actor}` },
    fields: parsed.fields,
  };
}
