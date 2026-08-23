// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Deciding a write before showing anything.
 *
 * The property under test: the board never puts a value on screen for a write
 * the room will not take. Returning a decision instead of performing one is
 * what makes that structural — a caller has nothing to display until this has
 * answered, so the old shape (show the value, then check whether the write was
 * allowed, then print the reason under a row that already moved) cannot be
 * written.
 */

import { describe, expect, it } from "vitest";
import { planFieldWrite } from "@/lib/board/write-plan";
import { RESERVED_FIELDS } from "@/lib/board/custody";
import type { LiveItem, SourceKind } from "@/lib/board/item";

const row = (kind: SourceKind, label = "work/auth-spike"): LiveItem => ({
  id: `${kind}:${label}`,
  title: label,
  source: { kind, label },
  fields: {},
});

describe("planFieldWrite", () => {
  it("names the memory and the frontmatter to put on it", () => {
    const plan = planFieldWrite(row("memory"), { status: "in_review" });
    expect(plan).toEqual({ key: "work/auth-spike", writable: { status: "in_review" } });
  });

  it("writes outside the leasable namespaces too", () => {
    // Custody is restricted to work/; a stage change is not. A decision nobody
    // can resolve is the same problem with extra steps.
    const plan = planFieldWrite(row("memory", "decisions/ttl"), { status: "resolved" });
    expect(plan).toMatchObject({ key: "decisions/ttl" });
  });

  it.each(["episode", "agent", "github"] as SourceKind[])(
    "refuses a %s row before there is anything to show",
    kind => {
      const plan = planFieldWrite(row(kind, "x"), { status: "resolved" });
      expect(plan).toHaveProperty("refused");
    },
  );

  it.each(RESERVED_FIELDS)("refuses %s, which a lease owns", name => {
    const plan = planFieldWrite(row("memory"), { [name]: "held" });
    expect(plan).toMatchObject({ refused: expect.stringContaining("lease") });
  });

  it("refuses the whole write when one key is reserved", () => {
    // A partly-applied write would land the half the guard did not catch.
    const plan = planFieldWrite(row("memory"), { status: "resolved", owner: "@mallory" });
    expect(plan).toHaveProperty("refused");
  });

  it("drops `updated`, which is the store's to stamp", () => {
    const plan = planFieldWrite(row("memory"), { status: "open", updated: "2026-01-01" });
    expect(plan).toEqual({ key: "work/auth-spike", writable: { status: "open" } });
  });

  it("has nothing to do when `updated` was the only field", () => {
    expect(planFieldWrite(row("memory"), { updated: "2026-01-01" })).toBeNull();
  });

  it("sends a cleared field as null, not by omitting it", () => {
    // `undefined` is dropped by JSON.stringify, so the key would survive the
    // write and the field would look cleared on screen only.
    const plan = planFieldWrite(row("memory"), { blocked_by: undefined });
    expect(plan).toEqual({ key: "work/auth-spike", writable: { blocked_by: null } });
  });

  it("has nothing to do for an empty patch", () => {
    expect(planFieldWrite(row("memory"), {})).toBeNull();
  });
});
