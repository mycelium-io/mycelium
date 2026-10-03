// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A fixture-backed stand-in for `GET /rooms/{room}/messages/search`.
 *
 * Same grammar, same shape, same disjunctive facet counts, over a room's mock
 * messages, so the find bar's History can be designed and shot with no hub.
 * Matching is the real thing's in miniature (words, phrases, `-word`, field
 * clauses, time bounds, sort); the fields that need the transcript (`to:`,
 * `stance:`, `kind:`) read what the fixtures carry and nothing more.
 */

import type { MockMessage, RoomFixture } from "./fixtures";
import { CLOSED_VALUES, canonical, type FacetBucket, type MessageSearchResponse, type SortOrder } from "@/lib/message-search";

const PROSE = new Set(["broadcast", "direct", "announce", "delegate"]);
const TOKEN = /(-?)(?:([A-Za-z][\w-]*):)?("([^"]*)"?|\S+)/g;
const AGE = /^(\d+)\s*(m|min|h|d|w)$/i;
const AGE_MS: Record<string, number> = { m: 60e3, min: 60e3, h: 3600e3, d: 86400e3, w: 604800e3 };

interface Clause {
  field: string;
  value: string;
  negate: boolean;
}

function time(raw: string, end = false): number | null {
  const text = raw.trim().toLowerCase();
  const age = AGE.exec(text);
  if (age) return Date.now() - Number(age[1]) * AGE_MS[age[2]];
  if (text === "today" || text === "yesterday") {
    const day = new Date();
    day.setUTCHours(0, 0, 0, 0);
    if (text === "yesterday") day.setUTCDate(day.getUTCDate() - 1);
    return day.getTime() + (end ? 86400e3 : 0);
  }
  const at = Date.parse(raw.length === 10 ? `${raw}T00:00:00Z` : raw);
  if (Number.isNaN(at)) return null;
  return at + (end && raw.length === 10 ? 86400e3 : 0);
}

interface Doc {
  m: MockMessage;
  task: string | null;
  thread: string | null;
  mentions: string[];
  values: Record<string, string[]>;
}

export function mockMessageSearch(fx: RoomFixture, raw: string, limit: number): MessageSearchResponse {
  const terms: string[] = [];
  const phrases: string[] = [];
  const excluded: string[] = [];
  const clauses: Clause[] = [];
  const problems: string[] = [];
  let after: number | null = null;
  let before: number | null = null;
  let sort: SortOrder = "newest";

  for (const m of raw.matchAll(TOKEN)) {
    const negate = m[1] === "-";
    const name = (m[2] ?? "").toLowerCase();
    const value = m[4] ?? m[3];
    const field = name ? canonical(name) : null;
    if (name && field && ["after", "since", "before", "until", "on"].includes(field)) {
      const start = time(value);
      const stop = time(value, true);
      if (start === null || stop === null) problems.push(m[0]);
      else if (field === "after" || field === "since") after = Math.max(after ?? 0, start);
      else if (field === "before" || field === "until") before = Math.min(before ?? Infinity, start);
      else {
        after = start;
        before = stop;
      }
      continue;
    }
    if (field === "sort") {
      if (["newest", "oldest", "relevance"].includes(value)) sort = value as SortOrder;
      else problems.push(m[0]);
      continue;
    }
    if (field) {
      if (!value) continue; // `from:` still being typed narrows nothing, as on the hub
      if (field in CLOSED_VALUES && !CLOSED_VALUES[field].includes(value.toLowerCase())) problems.push(m[0]);
      clauses.push({ field, value, negate });
      continue;
    }
    if (!name && value.startsWith("@") && value.length > 1 && m[4] === undefined) {
      clauses.push({ field: "from", value: value.slice(1), negate });
      continue;
    }
    const word = (name ? `${m[2]}:${value}` : value).toLowerCase();
    // `from:` with nothing after it yet narrows nothing, as on the hub.
    if (word.endsWith(":") && canonical(word.slice(0, -1)) !== null) continue;
    if (negate) excluded.push(word);
    else if (m[4] !== undefined && !name) phrases.push(word);
    else terms.push(word);
  }

  const rows = new Map<string, { key: string; title: string }>();
  for (const mem of fx.memories) {
    if (!mem.episode) continue;
    const text = typeof mem.value === "string" ? mem.value : (mem.content_text ?? mem.key);
    const title = (mem.meta?.title as string | undefined) ?? text.split("\n").find((l) => l.trim())?.replace(/^#\s*/, "") ?? mem.key;
    rows.set(mem.episode, { key: mem.key, title });
  }
  const titles = new Map([...rows.values()].map((r) => [r.key, r.title]));

  const named = new Set(clauses.filter((c) => c.field === "type" && !c.negate).map((c) => c.value));
  const docs: Doc[] = fx.messages
    .filter((m) => PROSE.has(m.message_type) || named.has(m.message_type))
    .map((m) => {
      const thread = m.episode && !m.episode.endsWith(":live") ? m.episode : null;
      const row = thread ? rows.get(thread) : undefined;
      const mentions = [...new Set([...m.content.matchAll(/(?:^|[\s(<])@([a-z0-9][\w.-]*)/gi)].map((x) => x[1]))];
      const has: string[] = [];
      if (mentions.length) has.push("mention");
      if (/https?:\/\//.test(m.content)) has.push("link");
      if (/\[\[[^\]]+\]\]|myc:\/\//.test(m.content)) has.push("memory");
      if (m.content.includes("`")) has.push("code");
      return {
        m,
        task: row?.key ?? null,
        thread,
        mentions,
        values: {
          from: [m.sender_handle],
          to: m.recipient_handle ? [m.recipient_handle] : [],
          mentions,
          task: row ? [row.key] : [],
          in: [thread ? "thread" : "channel"],
          type: [m.message_type],
          has,
          day: [m.created_at.slice(0, 10)],
        },
      };
    });

  const matches = (field: string, typed: string, value: string) => {
    const t = typed.toLowerCase().replace(/^@/, "");
    const v = value.toLowerCase();
    if (field === "task") return t === v || v.endsWith(`/${t}`) || (t.length > 2 && (titles.get(value) ?? "").toLowerCase().includes(t));
    return t === v;
  };
  const passes = (doc: Doc, field: string) => {
    const mine = clauses.filter((c) => c.field === field);
    const vals = doc.values[field] ?? [];
    if (mine.some((c) => c.negate && vals.some((v) => matches(field, c.value, v)))) return false;
    const wanted = mine.filter((c) => !c.negate);
    return wanted.length === 0 || wanted.some((c) => vals.some((v) => matches(field, c.value, v)));
  };

  const facetFields = ["from", "to", "mentions", "task", "in", "type", "has", "day"];
  const counts: Record<string, Map<string, number>> = Object.fromEntries(facetFields.map((f) => [f, new Map()]));
  const hits: { doc: Doc; score: number }[] = [];
  const clauseFields = [...new Set(clauses.map((c) => c.field))];
  for (const doc of docs) {
    const at = Date.parse(doc.m.created_at);
    if (after !== null && at < after) continue;
    if (before !== null && at >= before) continue;
    const text = doc.m.content.toLowerCase();
    if (excluded.some((x) => text.includes(x))) continue;
    if (![...terms, ...phrases].every((t) => text.includes(t))) continue;
    const failed = clauseFields.filter((f) => !passes(doc, f));
    if (failed.length > 1) continue;
    for (const f of facetFields) {
      if (failed.length === 0 || (failed.length === 1 && failed[0] === f)) {
        for (const v of new Set(doc.values[f] ?? [])) counts[f].set(v, (counts[f].get(v) ?? 0) + 1);
      }
    }
    if (failed.length === 0) {
      const score = [...terms, ...phrases].reduce((n, t) => n + text.split(t).length - 1, 0);
      hits.push({ doc, score });
    }
  }
  const at = (h: { doc: Doc }) => Date.parse(h.doc.m.created_at);
  if (sort === "oldest") hits.sort((a, b) => at(a) - at(b));
  else if (sort === "relevance") hits.sort((a, b) => b.score - a.score || at(b) - at(a));
  else hits.sort((a, b) => at(b) - at(a));

  const facets: Record<string, FacetBucket[]> = {};
  for (const f of facetFields) {
    const buckets = [...counts[f].entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 12)
      .map(([value, count]) => ({ value, label: f === "task" ? (titles.get(value) ?? value) : value, count }));
    if (buckets.length) facets[f] = buckets;
  }
  const needles = [...phrases, ...terms];
  const page = hits.slice(0, limit);
  return {
    query: raw,
    scope: {
      text: [...terms, ...phrases.map((p) => `"${p}"`)].join(" "),
      clauses,
      after: after !== null ? new Date(after).toISOString() : null,
      before: before !== null && Number.isFinite(before) ? new Date(before).toISOString() : null,
      sort,
      problems,
    },
    hits: page.map(({ doc, score }) => ({
      message: {
        id: doc.m.id,
        room_name: fx.room.name,
        sender_handle: doc.m.sender_handle,
        recipient_handle: doc.m.recipient_handle ?? null,
        message_type: doc.m.message_type,
        content: doc.m.content,
        metadata: doc.m.metadata ?? null,
        episode: doc.m.episode ?? null,
        created_at: doc.m.created_at,
      },
      snippet: snippet(doc.m.content, needles),
      score,
      task_key: doc.task,
      task_title: doc.task ? (titles.get(doc.task) ?? null) : null,
      thread: doc.thread,
      recipients: doc.values.to,
      mentions: doc.mentions,
      stance: null,
      context_before: [],
      context_after: [],
    })),
    total: hits.length,
    scanned: docs.length,
    facets,
    fields: ["from", "to", "mentions", "task", "in", "type", "kind", "status", "stance", "step", "is", "has", "day", "thread"],
    next_cursor: hits.length > page.length && page.length ? `${page[page.length - 1].doc.m.created_at}|${page[page.length - 1].doc.m.id}` : null,
  };
}

function snippet(text: string, needles: string[], width = 180): string {
  const flat = text.split(/\s+/).join(" ");
  if (flat.length <= width) return flat;
  const lower = flat.toLowerCase();
  const at = needles.map((n) => lower.indexOf(n)).filter((i) => i >= 0).sort((a, b) => a - b)[0] ?? -1;
  if (at < 0) return `${flat.slice(0, width).trimEnd()}…`;
  const start = Math.max(0, at - Math.floor(width / 3));
  return `${start > 0 ? "…" : ""}${flat.slice(start, start + width).trim()}${start + width < flat.length ? "…" : ""}`;
}
