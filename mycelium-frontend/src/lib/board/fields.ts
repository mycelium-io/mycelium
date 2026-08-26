// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Reading a row's frontmatter bag.
 *
 * Fields are untyped on purpose: a room can put anything in frontmatter, and a
 * row missing a field the triage likes still renders rather than crashing.
 *
 * These live below both `item` and `assignment` so neither has to import the other
 * to read a value — the derivations layer on the accessors, not on each other.
 * `item` re-exports them, so a caller still reads them where it always did.
 */

import type { LiveItem } from "./item";

/**
 * Why a row refuses a field write, in its own terms.
 *
 * A action that is not assignment writes frontmatter, and only a memory has any. The
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
  capture: "this row is not in the room yet; capture it first",
  github: "this value belongs to the tool it came from; change it there",
};

/** The only row kind with frontmatter behind it. */
export const WRITABLE_SOURCE_KINDS = ["memory"];

/**
 * Why a projected row has no thread to open, keyed by what produced it.
 *
 * The surface refuses in these terms rather than opening the room instead: a
 * pane that quietly showed a different conversation than the one asked for is
 * worse than one that did not open. Keyed by source kind, so an episode row is
 * absent — an episode *is* a thread, and its row always carries one.
 *
 * Frozen in `contracts/board-vocabulary.json` under `task.refusals`; the CLI
 * carries its own copy (`mycelium/board/model.py THREAD_REFUSALS`) and a test on
 * each side asserts against that file.
 */
export const THREAD_REFUSALS: Record<string, string> = {
  agent: "presence is a lease the runtime renews, not a conversation to join",
  memory: "the hub writes this memory for itself; a thread belongs to something a person authored",
};

/**
 * Why this row's thread cannot be opened, or null when it can.
 *
 * Every memory a person authored is minted a thread on creation, board
 * namespace or not, so a row all but always has one; the memory refusal is left
 * for what the hub writes for itself, which has no thread to open.
 */
export function threadRefusal(item: LiveItem, episode: string | null): string | null {
  if (episode) return null;
  return THREAD_REFUSALS[item.source.kind] ?? THREAD_REFUSALS.memory;
}

/** The memory key behind a row, or null when the row is not a memory. */
export function memoryKeyOf(item: LiveItem): string | null {
  return item.source.kind === "memory" ? item.id.replace(/^memory:/, "") : null;
}

/** Why this row cannot take a field write, or null when it can. */
export function fieldWriteRefusal(item: LiveItem): string | null {
  if (WRITABLE_SOURCE_KINDS.includes(item.source.kind)) return null;
  return FIELD_REFUSALS[item.source.kind] ?? "this row has no frontmatter to write";
}

export function fieldAsString(item: LiveItem, name: string): string | null {
  const v = item.fields[name];
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

export function fieldAsNumber(item: LiveItem, name: string): number | null {
  const v = item.fields[name];
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() && Number.isFinite(Number(v))) return Number(v);
  return null;
}

export function fieldAsList(item: LiveItem, name: string): string[] {
  const v = item.fields[name];
  if (Array.isArray(v)) return v.filter((x): x is string => typeof x === "string");
  if (typeof v === "string" && v.trim()) return [v.trim()];
  return [];
}

export function fieldAsBool(item: LiveItem, name: string): boolean {
  return item.fields[name] === true;
}

/** The row's holder, without the `@`. Absent means nobody, never "unknown". */
export function ownerOf(item: LiveItem): string | null {
  const o = fieldAsString(item, "owner");
  return o ? o.replace(/^@/, "") : null;
}
