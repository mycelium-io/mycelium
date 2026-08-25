// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Infer a typed schema from a set of frontmatter bags.
 *
 * Nothing declares the columns: the shape of a namespace is read back out of
 * what the markdown already carries, so a room that starts writing an
 * `assignee` field gets an assignee column, and a board can group by it, with
 * no migration and no config.
 */

import { ASSIGNMENT_STATES } from "./assignment";
import { THREAD_FIELDS } from "./projection";
import { STATUS_ORDER, type LiveItem } from "./item";
import { UPSTREAM_STATES } from "./upstream";

export type FieldType =
  | "select"
  | "handle"
  | "number"
  | "date"
  | "tags"
  | "checkbox"
  | "link"
  | "text";

export interface FieldOption {
  value: string;
  count: number;
}

export interface FieldSchema {
  name: string;
  label: string;
  type: FieldType;
  /** Distinct values, commonest first. Populated for select/handle/tags. */
  options: FieldOption[];
  /** How many records carry the field — drives column order and the "sparse" cue. */
  filled: number;
  total: number;
}

/** Fields the triage knows by name lead the table; the rest follow by fill rate. */
const PREFERRED_ORDER = [
  "status",
  "assignment",
  "kind",
  "owner",
  "priority",
  "upstream",
  "ci",
  "branch",
  "pr",
  "issue",
  "blocks",
  "blocked_by",
  "tags",
  "updated",
  "ttl_minutes",
];

/** Values that read as an enum whatever the room's vocabulary is. */
const MAX_SELECT_CARDINALITY = 12;

/**
 * Vocabularies the coordination layer defines rather than discovers. Inference
 * needs a value to repeat before it calls a field an enum — right for a room's
 * own fields, wrong for these, where a board must offer every column even when
 * a small room happens to use each state once.
 */
const KNOWN_VOCABULARIES: Record<string, string[]> = {
  status: [...STATUS_ORDER],
  assignment: [...ASSIGNMENT_STATES],
  kind: ["decision", "blocked", "review", "action", "concern", "signal"],
  priority: ["urgent", "high", "normal", "low"],
  ci: ["green", "running", "red"],
  upstream: [...UPSTREAM_STATES],
};

const ISO_DATE = /^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}|$)/;
const HANDLE = /^@[a-z0-9][a-z0-9._-]*$/i;
const LINKISH = /^(https?:\/\/|myc:\/\/|#\d+|[a-z0-9._-]+\/[a-z0-9._/-]+$)/i;

export function humanize(name: string): string {
  const spaced = name.replace(/[_-]+/g, " ").trim();
  if (!spaced) return name;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function classify(name: string, values: unknown[]): FieldType {
  const nonNull = values.filter(v => v !== null && v !== undefined && v !== "");
  if (nonNull.length === 0) return "text";

  const vocabulary = KNOWN_VOCABULARIES[name];
  if (vocabulary && nonNull.every(v => typeof v === "string" && vocabulary.includes(v))) return "select";

  if (nonNull.every(v => typeof v === "boolean")) return "checkbox";
  if (nonNull.some(v => Array.isArray(v))) return "tags";
  if (nonNull.every(v => typeof v === "number")) return "number";

  const strings = nonNull.filter((v): v is string => typeof v === "string");
  if (strings.length !== nonNull.length) return "text";

  if (strings.every(s => ISO_DATE.test(s))) return "date";
  if (strings.every(s => HANDLE.test(s))) return "handle";
  if (strings.every(s => Number.isFinite(Number(s)))) return "number";

  const distinct = new Set(strings);
  // An enum is a small vocabulary used more than once — a column of unique
  // one-liners is prose, however short, and grouping by it would make one
  // column per row.
  const repeats = strings.length - distinct.size > 0;
  const shortish = [...distinct].every(s => s.length <= 24);
  if (distinct.size <= MAX_SELECT_CARDINALITY && repeats && shortish) return "select";

  if (strings.every(s => LINKISH.test(s))) return "link";
  return "text";
}

function optionsFor(name: string, values: unknown[], type: FieldType): FieldOption[] {
  if (type !== "select" && type !== "handle" && type !== "tags" && type !== "checkbox") return [];
  const counts = new Map<string, number>();
  // A known vocabulary seeds its own zero-count options, so a column that
  // nothing is in yet is still a column you can drop work into.
  for (const value of KNOWN_VOCABULARIES[name] ?? []) counts.set(value, 0);
  const bump = (v: unknown) => {
    if (v === null || v === undefined || v === "") return;
    const key = typeof v === "boolean" ? String(v) : typeof v === "string" ? v : String(v);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  };
  for (const v of values) {
    if (Array.isArray(v)) v.forEach(bump);
    else bump(v);
  }
  const vocabulary = KNOWN_VOCABULARIES[name];
  const options = [...counts.entries()].map(([value, count]) => ({ value, count }));
  // A defined vocabulary keeps its own order (open → resolved reads as a
  // pipeline); a discovered one sorts by how much the room actually uses it.
  // A value outside the vocabulary sorts after every value in it: `indexOf`
  // returns -1, which would put the unexpected thing first, and the CLI puts it
  // last. The vocabulary is a deliberate order and something unexpected does not
  // belong in the middle of it, let alone at the front.
  const rank = (value: string) => {
    const i = vocabulary ? vocabulary.indexOf(value) : -1;
    return i === -1 ? (vocabulary?.length ?? 0) : i;
  };
  return vocabulary
    ? options.sort((a, b) => rank(a.value) - rank(b.value))
    : options.sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

/** The schema of a collection: one pass over every record's frontmatter. */
export function inferSchema(items: LiveItem[]): FieldSchema[] {
  const byName = new Map<string, unknown[]>();
  for (const item of items) {
    for (const [name, value] of Object.entries(item.fields)) {
      if (!byName.has(name)) byName.set(name, []);
      byName.get(name)!.push(value);
    }
  }

  const fields: FieldSchema[] = [];
  for (const [name, values] of byName) {
    const type = classify(name, values);
    const filled = values.filter(v => v !== null && v !== undefined && v !== "").length;
    fields.push({
      name,
      label: humanize(name),
      type,
      options: optionsFor(name, values, type),
      filled,
      total: items.length,
    });
  }

  return fields.sort((a, b) => {
    const ai = PREFERRED_ORDER.indexOf(a.name);
    const bi = PREFERRED_ORDER.indexOf(b.name);
    if (ai !== -1 || bi !== -1) {
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    }
    return b.filled - a.filled || a.name.localeCompare(b.name);
  });
}

/**
 * Fields a board can group into columns: a bounded vocabulary, ≥2 values, and
 * never one of the thread's.
 *
 * The thread fields are folded onto a row so they can be *read* — a column, a
 * chip — and grouping is not reading: it makes the field the axis the board is
 * organised by. Pivoting tasks by `thread_state` would sort them by how the
 * negotiation inside them went, which is the container-outlives-the-negotiation
 * rule inverted on the one surface where it is most visible. So the exclusion
 * is the whole of `THREAD_FIELDS` rather than the one field that reaches here
 * today: what makes them ineligible is whose fields they are, not their type.
 */
export function groupableFields(schema: FieldSchema[]): FieldSchema[] {
  return schema.filter(
    f =>
      !THREAD_FIELDS.includes(f.name) &&
      (f.type === "select" || f.type === "handle" || f.type === "checkbox") &&
      f.options.length >= 2,
  );
}

export function fieldByName(schema: FieldSchema[], name: string | null): FieldSchema | null {
  if (!name) return null;
  return schema.find(f => f.name === name) ?? null;
}
