// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Natural-language capture: one line in, a memory out.
 *
 * Capture is the human's only authoring gesture on this surface — everything
 * else self-populates — so it parses the sigils people already type in chat
 * rather than asking for a form.
 *
 * What it produces is a **memory**, written through the same upsert every other
 * write goes through. It is not a row the board invents and holds: a surface
 * that showed you a row the room had never been told about is the failure this
 * whole model exists to avoid, and a captured line that vanished on reload was
 * exactly that.
 */

import type { MemoryCreate } from "@/lib/api";

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

export function parseCapture(input: string, actor: string): ParsedCapture {
  const fields: Record<string, unknown> = {
    status: "open",
    priority: "normal",
    captured_by: `@${actor}`,
  };
  const hints: { label: string; value: string }[] = [];
  const tags: string[] = [];

  let title = input;

  const assignee = input.match(/(?:^|\s)@([a-z0-9][a-z0-9._-]*)/i);
  if (assignee) {
    // Naming somebody says who it is *for*. Custody is a lease they take, and
    // `owner` is the lease's field — writing it here would claim on their
    // behalf. The stage stays `open` either way: a task with a name on it is
    // still an open task.
    fields.assignee = `@${assignee[1]}`;
    fields.kind = "action";
    hints.push({ label: "for", value: `@${assignee[1]}` });
    title = title.replace(assignee[0], " ");
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
    // Nothing stores the word "blocked": a row is blocked because it *names* a
    // blocker, and the renderer reads `blocked_by`. Writing it as a status
    // would also be writing a value the vocabulary does not have.
    fields.issue = issue[1];
    fields.blocked_by = [issue[1]];
    hints.push({ label: "blocked by", value: issue[1] });
    title = title.replace(issue[0], " ");
  }

  // A question is a decision to route, not a task to do.
  if (/\?\s*$/.test(input.trim())) {
    fields.kind = "decision";
    hints.push({ label: "kind", value: "decision" });
  }

  return { title: title.replace(/\s{2,}/g, " ").trim(), fields, hints };
}

/** A readable, stable key fragment for a captured line. */
export function slugify(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48)
    .replace(/-+$/, "");
  return slug || "note";
}

/**
 * The memory a captured line becomes.
 *
 * A question routes to `decisions/`, because that is where the board reads a
 * decision from. Everything else lands in `work/` — the one namespace a lease
 * can be taken on, so a captured item is something somebody can actually pick
 * up rather than a note nobody can hold.
 */
export function captureToMemory(parsed: ParsedCapture, actor: string): MemoryCreate {
  const namespace = parsed.fields.kind === "decision" ? "decisions" : "work";
  const { tags, ...meta } = parsed.fields as { tags?: string[] } & Record<string, unknown>;
  return {
    key: `${namespace}/${slugify(parsed.title)}`,
    value: parsed.title,
    created_by: actor,
    tags,
    meta,
  };
}
