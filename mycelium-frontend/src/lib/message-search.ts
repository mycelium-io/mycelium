// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Searching a room's whole history from the channel's find bar.
 *
 * The hub parses and runs the query (`GET /rooms/{room}/messages/search`) and
 * echoes how it read it, so nothing here re-implements matching. What lives
 * here is what the find bar needs *while the query is being typed*: which
 * fields exist and what they mean, the word under the cursor, what it could
 * complete to, and which part of the query is plain words (what the loaded
 * messages are marked by). `contracts/message-search.json` freezes the words;
 * `message-search.test.ts` holds this copy to it.
 */

import type { Candidate, Slot } from "@/components/composer-hints";
import type { RoomMessage } from "@/lib/api";

// ── the response ────────────────────────────────────────────────────────────

export interface FacetBucket {
  value: string;
  label: string;
  count: number;
}

export interface MessageSearchHit {
  message: RoomMessage & { id: string; sender_handle: string; created_at: string; content: string };
  snippet: string;
  score: number;
  task_key: string | null;
  task_title: string | null;
  thread: string | null;
  recipients: string[];
  mentions: string[];
  stance: string | null;
  context_before: RoomMessage[];
  context_after: RoomMessage[];
}

export interface MessageSearchResponse {
  query: string;
  scope: {
    text: string;
    clauses: { field: string; value: string; negate: boolean }[];
    after: string | null;
    before: string | null;
    sort: SortOrder;
    problems: string[];
  };
  hits: MessageSearchHit[];
  total: number;
  scanned: number;
  facets: Record<string, FacetBucket[]>;
  fields: string[];
  next_cursor: string | null;
}

// ── the grammar ─────────────────────────────────────────────────────────────

export type SortOrder = "newest" | "oldest" | "relevance";

export interface FieldDoc {
  name: string;
  /** What a value looks like, for the signature: `<handle>`. */
  value: string;
  about: string;
}

/** Every field, in the order a person narrows by. */
export const FIELDS: FieldDoc[] = [
  { name: "from", value: "<handle>", about: "who said it (@handle is the same)" },
  { name: "to", value: "<handle>", about: "who it was addressed to" },
  { name: "mentions", value: "<handle>", about: "who it @-mentions" },
  { name: "task", value: "<task>", about: "said in this task's thread, by key or title" },
  { name: "in", value: "channel|thread", about: "said in the room, or inside a task" },
  { name: "type", value: "<type>", about: "the message's type" },
  { name: "kind", value: "<kind>", about: "an event's kind, or the message subkind it rode" },
  { name: "status", value: "<status>", about: "an event's ledger status" },
  { name: "stance", value: "accept|reject", about: "how the message landed" },
  { name: "step", value: "<step>", about: "the conductor step it belongs to" },
  { name: "is", value: "edited|conductor", about: "revised since it was sent, or a conductor post" },
  { name: "has", value: "mention|link|memory|code|scores", about: "what the message carries" },
  { name: "day", value: "<date>", about: "the UTC day it was said" },
  { name: "thread", value: "<episode>", about: "a thread by its episode id" },
];

export const ALIASES: Record<string, string> = {
  sender: "from",
  by: "from",
  author: "from",
  recipient: "to",
  mention: "mentions",
  row: "task",
  episode: "thread",
  date: "day",
};

export const TIME_KEYS: Record<string, string> = {
  after: "after",
  since: "after",
  before: "before",
  until: "before",
  on: "on",
};

export const SORTS: SortOrder[] = ["newest", "oldest", "relevance"];

export const CLOSED_VALUES: Record<string, string[]> = {
  in: ["channel", "thread"],
  is: ["edited", "conductor"],
  has: ["mention", "link", "memory", "code", "scores"],
  stance: ["accept", "reject"],
};

/** The scope words beside the fields: time bounds and the order. */
const SCOPE_DOCS: FieldDoc[] = [
  { name: "after", value: "<when>", about: "said at or after: 2h, 3d, today, 2026-09-03" },
  { name: "before", value: "<when>", about: "said before: 2h, 3d, yesterday, 2026-09-03" },
  { name: "on", value: "<day>", about: "said on this UTC day: today, yesterday, 2026-09-03" },
  { name: "sort", value: "newest|oldest|relevance", about: "the order hits come back in" },
];

const TIME_CHOICES: { value: string; about: string }[] = [
  { value: "1h", about: "an hour ago" },
  { value: "today", about: "since midnight UTC" },
  { value: "yesterday", about: "the day before" },
  { value: "2d", about: "two days ago" },
  { value: "1w", about: "a week ago" },
];

const SORT_ABOUT: Record<SortOrder, string> = {
  newest: "latest first (the default)",
  oldest: "earliest first",
  relevance: "best match first",
};

/** The field a typed name spells, a scope word, or null. */
export function canonical(name: string): string | null {
  const n = name.toLowerCase();
  if (FIELDS.some((f) => f.name === n)) return n;
  if (n in ALIASES) return ALIASES[n];
  if (n in TIME_KEYS || n === "sort") return n;
  return null;
}

/** A time word or alias as the scope it sets (`since` → `after`); anything else as itself. */
function scopeKey(name: string): string {
  return TIME_KEYS[name] ?? name;
}

function docOf(name: string): FieldDoc | undefined {
  const n = canonical(name);
  if (n === null) return undefined;
  const key = scopeKey(n);
  return [...FIELDS, ...SCOPE_DOCS].find((d) => d.name === key);
}

// ── reading the query as it is typed ────────────────────────────────────────

/** One token of the query, with where it sits. */
interface Token {
  start: number;
  end: number;
  text: string;
}

const TOKEN = /-?(?:[A-Za-z][\w-]*:)?(?:"[^"]*"?|\S+)/g;

function tokens(query: string): Token[] {
  return [...query.matchAll(TOKEN)].map((m) => ({ start: m.index ?? 0, end: (m.index ?? 0) + m[0].length, text: m[0] }));
}

/** A scope token — `field:value`, `after:2h`, `sort:oldest`, `@handle`. */
function isScope(token: string): boolean {
  const bare = token.replace(/^-/, "");
  if (/^@[\w.-]+$/.test(bare)) return true;
  const colon = bare.indexOf(":");
  return colon > 0 && canonical(bare.slice(0, colon)) !== null;
}

/**
 * The words and phrases of a query, scope taken out: what marks a hit inside
 * a loaded message. `from:avery apple "pay sheet"` marks `apple` and `pay sheet`.
 */
export function freeText(query: string): string[] {
  const out: string[] = [];
  for (const { text } of tokens(query)) {
    if (isScope(text) || text.startsWith("-")) continue;
    const word = text.replace(/^"|"$/g, "").trim();
    if (word) out.push(word);
  }
  return out;
}

/** Whether the query narrows by any field or time, not only by words. */
export function hasScope(query: string): boolean {
  return tokens(query).some((t) => isScope(t.text) && /:.|^-?@./.test(t.text.replace(/^-/, "")));
}

/** Whether the query asks for anything at all. */
export function isEmptyQuery(query: string): boolean {
  return query.trim().length === 0;
}

/**
 * Add `field:value` to the query, or take it out if it's already there, so a
 * facet is a switch. A value with a space in it is quoted.
 */
export function toggleClause(query: string, field: string, value: string): string {
  const shown = /\s/.test(value) ? `"${value}"` : value;
  const target = `${field}:${shown}`.toLowerCase();
  const kept = tokens(query).filter((t) => t.text.toLowerCase() !== target);
  if (kept.length !== tokens(query).length) return kept.map((t) => t.text).join(" ");
  return [query.trim(), `${field}:${shown}`].filter(Boolean).join(" ");
}

/** Whether `field:value` is in the query as a clause (not negated). */
export function hasClause(query: string, field: string, value: string): boolean {
  const shown = /\s/.test(value) ? `"${value}"` : value;
  const target = `${field}:${shown}`.toLowerCase();
  return tokens(query).some((t) => t.text.toLowerCase() === target);
}

/** Set the order, replacing a `sort:` already there (newest is the default, so it's dropped). */
export function withSort(query: string, sort: SortOrder): string {
  const kept = tokens(query).filter((t) => !/^sort:/i.test(t.text)).map((t) => t.text);
  if (sort !== "newest") kept.push(`sort:${sort}`);
  return kept.join(" ");
}

/** What the word under the cursor is, and what the hints should offer for it. */
export interface Hint {
  /** The span the picked candidate replaces. */
  start: number;
  end: number;
  candidates: Candidate[];
  /** The signature to draw: the field and its value, the one being typed lit. */
  signature: { head: string; slots: Slot[]; active: number; about: string } | null;
}

/** Values the hub has already seen for each field, from the last response's facets. */
export type Seen = Record<string, FacetBucket[]>;

function valueCandidates(field: string, typed: string, seen: Seen, handles: string[]): Candidate[] {
  const q = typed.replace(/^"/, "").toLowerCase();
  const match = (v: string, label = v) => !q || v.toLowerCase().includes(q) || label.toLowerCase().includes(q);
  const quoted = (v: string) => (/\s/.test(v) ? `"${v}"` : v);

  if (field in CLOSED_VALUES) {
    const counts = new Map((seen[field] ?? []).map((b) => [b.value, b.count]));
    return CLOSED_VALUES[field]
      .filter((v) => match(v))
      .map((v) => ({
        id: `${field}:${v}`,
        insert: `${field}:${v}`,
        primary: v,
        secondary: field,
        tertiary: counts.has(v) ? String(counts.get(v)) : undefined,
      }));
  }
  if (field === "sort") {
    return SORTS.filter((v) => match(v)).map((v) => ({ id: `sort:${v}`, insert: `sort:${v}`, primary: v, secondary: "sort", tertiary: SORT_ABOUT[v] }));
  }
  if (field === "after" || field === "before" || field === "on") {
    const days = (seen.day ?? []).map((b) => ({ value: b.value, about: String(b.count) }));
    const options = field === "on" ? [...TIME_CHOICES.filter((t) => !/\d[hmw]$/.test(t.value)), ...days] : [...TIME_CHOICES, ...days];
    return options.filter((o) => match(o.value)).slice(0, 8).map((o) => ({ id: `${field}:${o.value}`, insert: `${field}:${o.value}`, primary: o.value, secondary: field, tertiary: o.about }));
  }
  // A handle field offers who the room has heard from, then the roster.
  const buckets = seen[field] ?? [];
  const known = new Set(buckets.map((b) => b.value));
  const rows = buckets.map((b) => ({ value: b.value, label: b.label, about: String(b.count) }));
  if (field === "from" || field === "to" || field === "mentions") {
    for (const h of handles) if (!known.has(h)) rows.push({ value: h, label: h, about: "" });
  }
  return rows
    .filter((r) => match(r.value, r.label))
    .slice(0, 8)
    .map((r) => ({
      id: `${field}:${r.value}`,
      insert: `${field}:${quoted(r.value)}`,
      primary: r.label === r.value ? r.value : r.label,
      named: r.label !== r.value,
      secondary: field,
      tertiary: r.about || undefined,
    }));
}

/**
 * The hints for the word the cursor is in.
 *
 * A bare word that starts a field name offers the fields (`fr` → `from:`); a
 * `field:` offers its values — a closed field's set, the times worth typing,
 * and for the rest the values the room's messages actually carry, with how
 * many each has; `@` offers handles. A plain word offers nothing, so typing
 * an ordinary search is never interrupted.
 */
export function hintAt(query: string, cursor: number, seen: Seen, handles: string[] = []): Hint | null {
  const before = query.slice(0, cursor);
  const start = Math.max(before.lastIndexOf(" "), before.lastIndexOf("\t")) + 1;
  const after = query.slice(cursor).search(/\s/);
  const end = after < 0 ? query.length : cursor + after;
  const word = query.slice(start, cursor);
  const negate = word.startsWith("-") ? "-" : "";
  const bare = word.slice(negate.length);

  if (/^@[\w.-]*$/.test(bare)) {
    const candidates = valueCandidates("from", bare.slice(1), seen, handles).map((c) => ({
      ...c,
      insert: `${negate}${c.insert}`,
    }));
    const doc = docOf("from")!;
    return { start, end, candidates, signature: { head: "@", slots: [{ label: "<handle>", filled: bare.length > 1 }], active: 0, about: doc.about } };
  }

  const colon = bare.indexOf(":");
  if (colon > 0) {
    const name = bare.slice(0, colon);
    const field = canonical(name);
    if (field === null) return null;
    const value = bare.slice(colon + 1);
    const key = scopeKey(field);
    const doc = docOf(field);
    const candidates = valueCandidates(key, value, seen, handles).map((c) => ({
      ...c,
      // Keep the name as typed (an alias stays an alias) and the minus with it.
      insert: `${negate}${name}:${c.insert.slice(c.insert.indexOf(":") + 1)}`,
    }));
    return {
      start,
      end,
      candidates,
      signature: doc
        ? { head: `${negate}${name}:`, slots: [{ label: doc.value, filled: value.length > 0 }], active: 0, about: negate ? `not ${doc.about}` : doc.about }
        : null,
    };
  }

  if (/^[a-z]+$/i.test(bare)) {
    const typed = bare.toLowerCase();
    const candidates: Candidate[] = [...FIELDS, ...SCOPE_DOCS]
      .filter((d) => d.name.startsWith(typed))
      .map((d) => ({
        id: d.name,
        insert: `${negate}${d.name}:`,
        open: true,
        primary: `${negate}${d.name}:`,
        secondary: FIELDS.includes(d) ? "field" : "scope",
        tertiary: d.about,
      }));
    if (candidates.length === 0) return null;
    return { start, end, candidates, signature: null };
  }
  return null;
}
