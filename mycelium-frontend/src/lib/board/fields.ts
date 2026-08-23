// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Reading a row's frontmatter bag.
 *
 * Fields are untyped on purpose: a room can put anything in frontmatter, and a
 * row missing a field the cockpit likes still renders rather than crashing.
 *
 * These live below both `item` and `custody` so neither has to import the other
 * to read a value — the derivations layer on the accessors, not on each other.
 * `item` re-exports them, so a caller still reads them where it always did.
 */

import type { LiveItem } from "./item";

/**
 * Why a row refuses a field write, in its own terms.
 *
 * A verb that is not custody writes frontmatter, and only a memory has any. The
 * rest of the board is projected out of state that lives elsewhere — a
 * checklist line, an episode record, a presence lease — so there is nothing to
 * write onto, and saying that beats accepting a write that goes nowhere.
 *
 * Frozen in `contracts/board-vocabulary.json` under `fields`; the CLI carries
 * its own copy and a test on each side asserts against that file.
 */
export const FIELD_REFUSALS: Record<string, string> = {
  episode: "an episode is a recorded negotiation, not a row the room can edit",
  agent: "presence is what the runtime reports, not a field you set",
  github: "this value belongs to the tool it came from; change it there",
};

/** The only row kind with frontmatter behind it. */
export const WRITABLE_SOURCE_KINDS = ["memory"];

/** The memory key behind a row, or null when the row is not a memory. */
export function memoryKeyOf(item: LiveItem): string | null {
  return item.source.kind === "memory" ? item.id.replace(/^memory:/, "") : null;
}

/** Why this row cannot take a field write, or null when it can. */
export function fieldWriteRefusal(item: LiveItem): string | null {
  if (WRITABLE_SOURCE_KINDS.includes(item.source.kind)) return null;
  return FIELD_REFUSALS[item.source.kind] ?? "this row has no frontmatter to write";
}

export function str(item: LiveItem, name: string): string | null {
  const v = item.fields[name];
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

export function num(item: LiveItem, name: string): number | null {
  const v = item.fields[name];
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() && Number.isFinite(Number(v))) return Number(v);
  return null;
}

export function arr(item: LiveItem, name: string): string[] {
  const v = item.fields[name];
  if (Array.isArray(v)) return v.filter((x): x is string => typeof x === "string");
  if (typeof v === "string" && v.trim()) return [v.trim()];
  return [];
}

export function bool(item: LiveItem, name: string): boolean {
  return item.fields[name] === true;
}

/** The row's holder, without the `@`. Absent means nobody, never "unknown". */
export function ownerOf(item: LiveItem): string | null {
  const o = str(item, "owner");
  return o ? o.replace(/^@/, "") : null;
}

