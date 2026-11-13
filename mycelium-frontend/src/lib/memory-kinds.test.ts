// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Contract drift guard for memory kinds (frontend side). The hub refuses every
// write the table in contracts/memory-kinds.json doesn't allow; the editor
// offers Edit from this copy, so a kind the hub made read-only would otherwise
// still open an editor whose save is refused.

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { kindOf, MEMORY_KINDS, notEditable } from "@/lib/memory-kinds";

const contract = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../../contracts/memory-kinds.json"), "utf-8"),
) as { kinds: { id: string; patterns: string[]; edit: string; source?: string; says?: string }[] };

describe("memory kinds contract", () => {
  it("has every kind the hub has, in its order, with its patterns and what may be edited", () => {
    expect(MEMORY_KINDS).toEqual(
      contract.kinds.map(({ id, patterns, edit, source, says }) => ({
        id,
        patterns,
        edit,
        ...(source ? { source } : {}),
        ...(says ? { says } : {}),
      })),
    );
  });
});

describe("kindOf", () => {
  it("takes the first kind whose pattern matches", () => {
    expect(kindOf("uploads/plan.md").id).toBe("upload");
    expect(kindOf("agents/builder").id).toBe("agent");
    expect(kindOf("agents/builder/notes").id).toBe("memory");
    expect(kindOf("work/ship-it/part").id).toBe("task");
    expect(kindOf("context/summary/ship-it").id).toBe("summary");
    expect(kindOf("context/plan").id).toBe("memory");
  });

  it("says why a kind isn't edited here, and nothing for one that is", () => {
    expect(notEditable(kindOf("uploads/plan.md"))).toMatch(/Upload the file again/);
    expect(notEditable(kindOf("context/summary/ship-it"))).toMatch(/`contract` field/);
    expect(notEditable(kindOf("context/plan"))).toBeNull();
  });
});
