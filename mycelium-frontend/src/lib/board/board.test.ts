// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { inferSchema, groupableFields } from "@/lib/board/schema";
import { projectItems } from "@/lib/board/projection";
import { applyView, filterItems, lensCounts, DEFAULT_VIEW } from "@/lib/board/view";
import {
  applyVerb,
  lensOf,
  LENSES,
  PRIORITY_ORDER,
  STATUS_ORDER,
  VERBS,
  type LiveItem,
} from "@/lib/board/item";
import { parseCapture } from "@/lib/board/capture";
import type { PlanResponse } from "@/lib/api";

const item = (id: string, fields: Record<string, unknown>): LiveItem => ({
  id,
  title: id,
  source: { kind: "memory", label: id },
  fields,
});

describe("inferSchema", () => {
  it("reads a room's own repeated vocabulary as a select, commonest first", () => {
    const schema = inferSchema([
      item("a", { severity: "sev2" }),
      item("b", { severity: "sev2" }),
      item("c", { severity: "sev1" }),
    ]);
    const severity = schema.find(f => f.name === "severity");
    expect(severity?.type).toBe("select");
    expect(severity?.options).toEqual([
      { value: "sev2", count: 2 },
      { value: "sev1", count: 1 },
    ]);
  });

  it("offers a defined vocabulary whole, in its own order, however little a room uses it", () => {
    const schema = inferSchema([item("a", { status: "open" })]);
    const status = schema.find(f => f.name === "status");
    expect(status?.type).toBe("select");
    expect(status?.options.map(o => o.value)).toEqual([
      "open",
      "claimed",
      "in_progress",
      "in_review",
      "blocked",
      "resolved",
      "dismissed",
    ]);
    expect(status?.options.find(o => o.value === "claimed")?.count).toBe(0);
  });

  it("keeps one-off prose as text, so grouping can't make a column per row", () => {
    const schema = inferSchema([
      item("a", { note: "the aligner stalled on a prose reply" }),
      item("b", { note: "cache TTL sweep needs a second pass" }),
    ]);
    expect(schema.find(f => f.name === "note")?.type).toBe("text");
  });

  it("types handles, dates, numbers, tags and checkboxes apart", () => {
    const schema = inferSchema([
      item("a", { owner: "@julia", updated: "2026-08-20T10:00:00Z", rounds: 3, tags: ["auth"], live: true }),
      item("b", { owner: "@agent-y", updated: "2026-08-21T10:00:00Z", rounds: 5, tags: ["auth", "jwt"], live: false }),
    ]);
    const byName = Object.fromEntries(schema.map(f => [f.name, f.type]));
    expect(byName).toMatchObject({
      owner: "handle",
      updated: "date",
      rounds: "number",
      tags: "tags",
      live: "checkbox",
    });
  });

  it("offers only bounded fields as kanban columns", () => {
    const schema = inferSchema([
      item("a", { status: "open", title_line: "one" }),
      item("b", { status: "blocked", title_line: "two" }),
    ]);
    expect(groupableFields(schema).map(f => f.name)).toEqual(["status"]);
  });
});

describe("projectItems", () => {
  const plan: PlanResponse = {
    room: "atlas",
    title: "Atlas",
    files: [
      { slug: "tasks", title: "Cutover", content: "", updated_at: "2026-08-20T10:00:00Z", updated_by: "aligner", tasks: [] },
    ],
    tasks: [
      { id: "t1", slug: "tasks", line: 2, text: "flip reads behind a flag @growth", done: false },
      { id: "t2", slug: "tasks", line: 3, text: "retire the legacy store @risk", done: true },
    ],
    open_count: 1,
    done_count: 1,
  };

  const projected = () =>
    projectItems({
      room: "atlas",
      plan,
      episodes: [],
      memories: [],
      agents: [],
      presence: new Map(),
      now: "2026-08-22T10:00:00Z",
    });

  it("lifts a plan task's @handle into an owner and its state into a status", () => {
    const [open, done] = projected();
    expect(open.fields).toMatchObject({ owner: "@growth", status: "in_progress" });
    expect(open.title).toBe("flip reads behind a flag");
    expect(done.fields.status).toBe("resolved");
  });

  it("keeps provenance on every row", () => {
    expect(projected()[0].source).toEqual({ kind: "plan", label: "plan/tasks.md:2" });
  });

  it("lets a local triage overlay win over the projected value", () => {
    const items = projectItems({
      room: "atlas",
      plan,
      episodes: [],
      memories: [],
      agents: [],
      presence: new Map(),
      now: "2026-08-22T10:00:00Z",
      overlay: { "plan:t1": { status: "blocked" } },
    });
    expect(items[0].fields.status).toBe("blocked");
  });
});

describe("lenses", () => {
  it("derives the lens from status rather than storing it", () => {
    expect(lensOf(item("a", { status: "open" }))).toBe("needs_you");
    expect(lensOf(item("b", { status: "blocked" }))).toBe("needs_you");
    expect(lensOf(item("c", { status: "in_progress" }))).toBe("in_flight");
    expect(lensOf(item("d", { status: "resolved" }))).toBe("resolved");
  });

  it("counts every lens off the unfiltered set", () => {
    const counts = lensCounts([
      item("a", { status: "open" }),
      item("b", { status: "in_progress" }),
      item("c", { status: "resolved" }),
    ]);
    expect(counts).toEqual({ needs_you: 1, in_flight: 1, resolved: 1, all: 3 });
  });

  it("shows only the lens asked for", () => {
    const items = [item("a", { status: "open" }), item("b", { status: "in_progress" })];
    expect(filterItems(items, { ...DEFAULT_VIEW, lens: "in_flight" }).map(i => i.id)).toEqual(["b"]);
  });
});

describe("applyView", () => {
  const items = [
    item("a", { status: "open", kind: "decision", priority: "urgent", updated: "2026-08-22T09:00:00Z" }),
    item("b", { status: "blocked", kind: "blocked", priority: "normal", updated: "2026-08-22T08:00:00Z" }),
    item("c", { status: "in_progress", kind: "action", priority: "high", updated: "2026-08-22T09:30:00Z" }),
  ];
  const now = Date.parse("2026-08-22T10:00:00Z");

  it("groups the steer-lens by kind, urgent first", () => {
    const groups = applyView(items, DEFAULT_VIEW, inferSchema(items), now);
    expect(groups.map(g => g.label)).toEqual(["Decisions", "Blocked"]);
    expect(groups[0].items[0].id).toBe("a");
  });

  it("renders an empty column so a kanban is somewhere to drop work", () => {
    const config = { ...DEFAULT_VIEW, mode: "board" as const, lens: "all" as const, groupBy: "status", showResolved: true };
    const groups = applyView(items, config, inferSchema(items), now);
    expect(groups.some(g => g.items.length === 0)).toBe(true);
  });

  it("matches a query against fields as well as the title", () => {
    const config = { ...DEFAULT_VIEW, lens: "all" as const, query: "blocked" };
    expect(filterItems(items, config).map(i => i.id)).toEqual(["b"]);
  });
});

describe("applyVerb", () => {
  it("claims for the actor when the row is unowned", () => {
    const patch = applyVerb(item("a", { status: "open" }), "claim", { actor: "julia", now: "t" });
    expect(patch).toMatchObject({ status: "in_progress", owner: "julia" });
  });

  it("leaves the owner alone when the row already has one", () => {
    const patch = applyVerb(item("a", { status: "open", owner: "@agent-y" }), "claim", { actor: "julia", now: "t" });
    expect(patch.owner).toBe("agent-y");
  });

  it("promote stamps the back-link and drops the row off the live board", () => {
    const patch = applyVerb(item("a", { status: "open" }), "promote", { actor: "julia", now: "t", issueNumber: 704 });
    expect(patch).toMatchObject({ status: "resolved", promoted: true, issue: "#704" });
  });
});

describe("parseCapture", () => {
  const now = "2026-08-22T10:00:00Z";

  it("routes an @handle to an owner and claims the row", () => {
    const parsed = parseCapture("rotate the signing key @agent-z", "julia", now);
    expect(parsed.title).toBe("rotate the signing key");
    expect(parsed.fields).toMatchObject({ owner: "@agent-z", status: "claimed", kind: "action" });
  });

  it("reads a question as a decision to route, not a task to do", () => {
    expect(parseCapture("15m or 60m TTL?", "julia", now).fields).toMatchObject({
      kind: "decision",
      status: "open",
    });
  });

  it("treats a bare issue reference as what the row waits on", () => {
    const parsed = parseCapture("thin-spoke join #502", "julia", now);
    expect(parsed.fields).toMatchObject({ status: "blocked", blocked_by: ["#502"], issue: "#502" });
  });

  it("lifts bangs and #tags out of the title", () => {
    const parsed = parseCapture("audit the custody store !! #security", "julia", now);
    expect(parsed.title).toBe("audit the custody store");
    expect(parsed.fields).toMatchObject({ priority: "urgent", tags: ["security"] });
  });

  it("gives a captured row a TTL, so an unclaimed concern expires", () => {
    expect(parseCapture("something smells here", "julia", now).fields.ttl_minutes).toBe(2880);
  });
});

describe("shared vocabulary contract", () => {
  // The CLI carries its own copy of these words (mycelium-cli/src/mycelium/board/)
  // and asserts the same file, so neither surface can rename a status, a lens or
  // a verb without turning a gate red on both sides.
  const contract = JSON.parse(
    readFileSync(join(__dirname, "..", "..", "..", "..", "contracts", "board-vocabulary.json"), "utf8"),
  ) as {
    statuses: string[];
    kinds: string[];
    priorities: string[];
    lenses: string[];
    verbs: string[];
    lens_of_status: Record<string, string>;
    verb_keys: Record<string, string>;
  };

  it("uses the contracted statuses, kinds, priorities and lenses", () => {
    expect(STATUS_ORDER).toEqual(contract.statuses);
    expect(PRIORITY_ORDER).toEqual(contract.priorities);
    expect(LENSES.map(l => l.id)).toEqual(contract.lenses);
  });

  it("derives every contracted status into the lens the contract names", () => {
    for (const [status, lens] of Object.entries(contract.lens_of_status)) {
      expect(lensOf(item(status, { status }))).toBe(lens);
    }
  });

  it("binds each verb to the contracted key", () => {
    expect(Object.fromEntries(VERBS.map(v => [v.id, v.key]))).toEqual(contract.verb_keys);
    for (const verb of VERBS) expect(contract.verbs).toContain(verb.id);
  });

  it("offers the contracted status vocabulary as select options", () => {
    const schema = inferSchema([item("a", { status: "open" })]);
    expect(schema.find(f => f.name === "status")?.options.map(o => o.value)).toEqual(contract.statuses);
  });
});
