// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Field writes: the board's row actions, and where each one is allowed to land.
 *
 * The property under test is that the board never accepts a change it cannot
 * put in the room. A status set in the browser and nowhere else is a surface
 * asserting something the room was never told, which is the failure that made
 * every action but assignment an optimistic edit in the first place.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  FIELD_REFUSALS,
  WRITABLE_SOURCE_KINDS,
  fieldWriteRefusal,
  memoryKeyOf,
} from "@/lib/board/fields";
import {
  ASSIGNMENT_COMPANION_FIELDS,
  ASSIGNMENT_FIELD,
  RESERVED_FIELDS,
  reservedIn,
} from "@/lib/board/assignment";
import { applyRowAction, type LiveItem, type SourceKind } from "@/lib/board/item";

const VOCAB = JSON.parse(
  readFileSync(join(process.cwd(), "..", "contracts", "board-vocabulary.json"), "utf8"),
);
const CONTRACT = VOCAB.fields;

const row = (kind: SourceKind, label: string, fields: Record<string, unknown> = {}): LiveItem => ({
  id: `${kind}:${label}`,
  title: label,
  source: { kind, label },
  fields,
});

describe("the fields contract", () => {
  it("refuses the kinds the CLI refuses, in the same words", () => {
    expect(FIELD_REFUSALS).toEqual(CONTRACT.refusals);
  });

  it("agrees on which rows have frontmatter behind them", () => {
    expect(WRITABLE_SOURCE_KINDS).toEqual(CONTRACT.writable_source_kinds);
  });

  it("derives the reserved set from assignment rather than restating it", () => {
    // The contract deliberately carries no second copy of these: a lease owns
    // them, so they are read out of the assignment block.
    expect(RESERVED_FIELDS).toEqual([ASSIGNMENT_FIELD, "owner", ...ASSIGNMENT_COMPANION_FIELDS]);
    expect(RESERVED_FIELDS).toEqual([
      VOCAB.assignment.field,
      "owner",
      ...VOCAB.assignment.companion_fields,
    ]);
  });
});

describe("where a field write may land", () => {
  it("accepts a memory row", () => {
    expect(fieldWriteRefusal(row("memory", "work/auth-spike"))).toBeNull();
    expect(memoryKeyOf(row("memory", "work/auth-spike"))).toBe("work/auth-spike");
  });

  it.each(["episode", "agent", "capture", "github"] as SourceKind[])(
    "refuses a %s row, and says why",
    kind => {
      const refusal = fieldWriteRefusal(row(kind, "x"));
      expect(refusal).toBe(FIELD_REFUSALS[kind]);
      expect(refusal).toBeTruthy();
      expect(memoryKeyOf(row(kind, "x"))).toBeNull();
    },
  );

  it("refuses an unknown kind rather than writing it somewhere", () => {
    // A new SourceKind added without a refusal must not fall through to a write.
    expect(fieldWriteRefusal(row("wormhole" as SourceKind, "x"))).toBeTruthy();
  });
});

describe("what a lease owns", () => {
  it.each(RESERVED_FIELDS)("reports %s as a lease's to move", name => {
    expect(reservedIn([name])).toEqual([name]);
  });

  it("lets an ordinary field through", () => {
    expect(reservedIn(["status", "priority", "blocked_by", "assignee"])).toEqual([]);
  });

  it("names every clash, not just the first", () => {
    expect(reservedIn(["status", "owner", "assignment"])).toEqual(["assignment", "owner"]);
  });
});

describe("the row actions that are field writes", () => {
  const item = row("memory", "work/auth-spike");
  const ctx = { actor: "julia", now: "2026-08-23T12:00:00Z" };

  it.each(["block", "unblock", "dismiss", "promote"] as const)(
    "%s writes nothing a lease owns",
    action => {
      const patch = applyRowAction(item, action, ctx);
      expect(reservedIn(Object.keys(patch))).toEqual([]);
    },
  );

  it("does not invent a GitHub back-link when promoting", () => {
    // A synthetic issue number was survivable as an optimistic edit. Written to the
    // room it is a fabricated reference the upstream provider would resolve
    // against a real, unrelated issue.
    const patch = applyRowAction(item, "promote", ctx);
    expect(patch.promoted).toBe(true);
    expect(patch.issue).toBeUndefined();
  });

  it("clears a blocker with null rather than by dropping the key", () => {
    // `undefined` would be dropped by JSON.stringify and the field would
    // silently survive the write.
    expect(applyRowAction(item, "unblock", ctx).blocked_by).toBeNull();
  });
});
