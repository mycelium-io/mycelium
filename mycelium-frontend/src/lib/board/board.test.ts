// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { inferSchema, groupableFields } from "@/lib/board/schema";
import { projectItems, EPISODE_FIELD, THREAD_FIELDS, THREAD_STATES, UNIT_FIELDS } from "@/lib/board/projection";
import { applyView, filterItems, lensCounts, groupItems, UNGROUPED, DEFAULT_VIEW } from "@/lib/board/view";
import { CUSTODY_STATES, DEFAULT_TTL_MINUTES, custodyOf } from "@/lib/board/custody";
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
import { DAILY_GOAL, heatLevel, weekdayIndex } from "@/lib/board/activity";
import { attachUpstream, UPSTREAM_STATES, upstreamAge, type RoomStatus } from "@/lib/board/upstream";

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
      "in_review",
      "resolved",
      "dismissed",
    ]);
    expect(status?.options.find(o => o.value === "dismissed")?.count).toBe(0);
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
      item("b", { status: "in_review", title_line: "two" }),
    ]);
    expect(groupableFields(schema).map(f => f.name)).toEqual(["status"]);
  });

  it("offers custody as a column, so a board can group by who holds what", () => {
    const schema = inferSchema([item("a", { custody: "held" })]);
    const custody = schema.find(f => f.name === "custody");
    expect(custody?.type).toBe("select");
    expect(custody?.options.map(o => o.value)).toEqual([...CUSTODY_STATES]);
  });
});

describe("projectItems", () => {
  //: The two rows an agreement compiles into: one open and assigned, one done.
  const memories = [
    {
      key: "work/flip-reads-behind-a-flag",
      value: "flip reads behind a flag",
      meta: { kind: "action", status: "open", assignee: "@growth" },
      version: 1,
      created_by: "aligner",
      updated_by: "aligner",
      updated_at: "2026-08-20T10:00:00Z",
    },
    {
      key: "work/retire-the-legacy-store",
      value: "retire the legacy store",
      meta: { kind: "action", status: "resolved", assignee: "@risk" },
      version: 1,
      created_by: "aligner",
      updated_by: "aligner",
      updated_at: "2026-08-20T10:00:00Z",
    },
  ] as unknown as Parameters<typeof projectItems>[0]["memories"];

  const projected = () =>
    projectItems({
      room: "atlas",
      episodes: [],
      memories,
      agents: [],
      presence: new Map(),
      now: "2026-08-22T10:00:00Z",
    });

  it("names who a compiled task is for without claiming it", () => {
    const [open, done] = projected();
    // An assignment is not a lease: the row stays unclaimed until somebody
    // takes it, so nothing asserts a holder who never agreed to hold it.
    expect(open.fields).toMatchObject({ assignee: "@growth", status: "open" });
    expect(open.fields.owner).toBeNull();
    expect(custodyOf(open, Date.parse("2026-08-22T10:00:00Z"))).toBe("unclaimed");
    expect(open.title).toBe("flip reads behind a flag");
    expect(done.fields.status).toBe("resolved");
  });

  it("keeps provenance on every row", () => {
    expect(projected()[0].source).toMatchObject({
      kind: "memory",
      label: "work/flip-reads-behind-a-flag",
    });
  });

  it("lets a local triage overlay win over the projected value", () => {
    const items = projectItems({
      room: "atlas",
      episodes: [],
      memories,
      agents: [],
      presence: new Map(),
      now: "2026-08-22T10:00:00Z",
      overlay: { "memory:work/flip-reads-behind-a-flag": { status: "dismissed" } },
    });
    expect(items[0].fields.status).toBe("dismissed");
  });
});

describe("a unit of work is one row, and it is a thread", () => {
  const NOW = "2026-08-22T10:00:00Z";
  const URN = "urn:ioc:mycelium:episode:atlas:e4f1a2";

  const episode = {
    short_id: "e4f1a2",
    episode: URN,
    topic: "urn:concept:mycelium:atlas",
    outcome: "converged",
    subkind: "converged",
    participants: ["growth", "risk"],
    metrics: null,
    assignments: { cutover: "phased" },
    tasks: ["work/cutover"],
    message_count: 7,
    updated_at: NOW,
    updated_by: "aligner",
  } as unknown as Parameters<typeof projectItems>[0]["episodes"][number];

  const unit = (extra: Record<string, unknown> = {}) => ({
    key: "work/cutover",
    value: "run the cutover",
    meta: { kind: "action", status: "open", ...extra },
    version: 1,
    created_by: "aligner",
    updated_by: "aligner",
    updated_at: NOW,
    episode: URN,
  }) as unknown as Parameters<typeof projectItems>[0]["memories"][number];

  const project = (episodes: unknown[], memories: unknown[]) =>
    projectItems({
      room: "atlas",
      episodes: episodes as Parameters<typeof projectItems>[0]["episodes"],
      memories: memories as Parameters<typeof projectItems>[0]["memories"],
      agents: [],
      presence: new Map(),
      now: NOW,
    });

  it("folds a bound episode into the row instead of drawing a second one", () => {
    const items = project([episode], [unit()]);
    expect(items).toHaveLength(1);
    expect(items[0].id).toBe("memory:work/cutover");
    expect(items[0].fields).toMatchObject({
      episode: URN,
      thread: "e4f1a2",
      thread_state: "converged",
      participants: ["growth", "risk"],
      rounds: 7,
    });
  });

  it("leaves a unit's own axes alone when the thread inside it closes", () => {
    // The container outlives the negotiation. A converged episode is a fact
    // about the conversation, not a claim that the work is done or that anyone
    // is holding it — the row keeps its status, its custody and its holder.
    const held = { custody: "held", owner: "@growth", claimed_at: NOW, ttl_minutes: 30 };
    const [row] = project([episode], [unit(held)]);
    expect(row.fields).toMatchObject({ status: "open", custody: "held", owner: "@growth" });
    expect(custodyOf(row, Date.parse(NOW))).toBe("held");
  });

  it("keeps an orphaned episode as a row of its own", () => {
    // A recorded negotiation nobody compiled into work is still something the
    // room did, so it is surfaced rather than hidden or deleted.
    const items = project([episode], []);
    expect(items.map(i => i.id)).toEqual(["episode:e4f1a2"]);
    expect(items[0].fields).toMatchObject({ episode: URN, thread: "e4f1a2" });
  });

  it("gives every row an episode compiled out of the same negotiation", () => {
    const second = { ...unit(), key: "work/soak" };
    const items = project([episode], [unit(), second]);
    expect(items.map(i => i.id)).toEqual(["memory:work/cutover", "memory:work/soak"]);
    for (const row of items) expect(row.fields.thread_state).toBe("converged");
  });

  it("draws a unit no thread has run in yet, with no thread state to show", () => {
    // The inversion: a unit is created board-first and worked with no episode
    // ever opened. It carries its binding and says nothing it doesn't know.
    const [row] = project([], [unit()]);
    expect(row.fields).toMatchObject({ episode: URN, thread: "e4f1a2", status: "open" });
    expect(row.fields.thread_state).toBeUndefined();
    expect(row.fields.rounds).toBeUndefined();
  });

  it("leaves a row with no binding entirely alone", () => {
    const unbound = { ...unit(), episode: null };
    const [row] = project([], [unbound]);
    expect(row.fields.episode).toBeUndefined();
    expect(row.fields.thread).toBeUndefined();
  });
});

describe("lenses", () => {
  const now = Date.parse("2026-08-22T10:00:00Z");
  const heldNow = { custody: "held", owner: "@growth", claimed_at: "2026-08-22T09:55:00Z", ttl_minutes: 30 };

  it("derives the lens from status where nobody holds the row", () => {
    expect(lensOf(item("a", { status: "open" }), now)).toBe("needs_you");
    expect(lensOf(item("d", { status: "in_review" }), now)).toBe("in_flight");
    expect(lensOf(item("e", { status: "resolved" }), now)).toBe("resolved");
  });

  it("puts custody ahead of the stage, because a holder is the sharper fact", () => {
    expect(lensOf(item("b", heldNow), now)).toBe("in_flight");
    expect(lensOf(item("c", { custody: "released" }), now)).toBe("needs_you");
  });

  it("is blocked because the row names a blocker, whoever holds it", () => {
    expect(lensOf(item("f", { ...heldNow, blocked_by: ["#502"] }), now)).toBe("needs_you");
  });

  it("counts every lens off the unfiltered set", () => {
    const counts = lensCounts(
      [item("a", { status: "open" }), item("b", heldNow), item("c", { status: "resolved" })],
      now,
    );
    expect(counts).toEqual({ needs_you: 1, in_flight: 1, resolved: 1, all: 3 });
  });

  it("shows only the lens asked for", () => {
    const items = [item("a", { status: "open" }), item("b", heldNow)];
    expect(filterItems(items, { ...DEFAULT_VIEW, lens: "in_flight" }, now).map(i => i.id)).toEqual([
      "b",
    ]);
  });
});

describe("applyView", () => {
  const items = [
    item("a", { status: "open", kind: "decision", priority: "urgent", updated: "2026-08-22T09:00:00Z" }),
    item("b", { status: "open", kind: "blocked", priority: "normal", blocked_by: ["#502"], updated: "2026-08-22T08:00:00Z" }),
    item("c", {
      custody: "held",
      owner: "@growth",
      claimed_at: "2026-08-22T09:50:00Z",
      ttl_minutes: 30,
      kind: "action",
      priority: "high",
      updated: "2026-08-22T09:30:00Z",
    }),
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
    const config = { ...DEFAULT_VIEW, lens: "all" as const, query: "#502" };
    expect(filterItems(items, config, now).map(i => i.id)).toEqual(["b"]);
  });
});

describe("applyVerb", () => {
  const stamp = "2026-08-22T10:00:00Z";

  it("claims for the actor as a lease, not as a stage", () => {
    const patch = applyVerb(item("a", { status: "open" }), "claim", { actor: "julia", now: stamp });
    expect(patch).toMatchObject({
      custody: "held",
      owner: "@julia",
      claimed_at: stamp,
      ttl_minutes: DEFAULT_TTL_MINUTES,
    });
    // The stage is untouched: a claim says who is on it, not how far along it is.
    expect(patch.status).toBeUndefined();
  });

  it("leaves the owner alone when the row already has one", () => {
    const patch = applyVerb(item("a", { status: "open", owner: "@agent-y" }), "claim", {
      actor: "julia",
      now: stamp,
    });
    expect(patch.owner).toBe("@agent-y");
  });

  it("releasing clears the holder and signs a note", () => {
    const patch = applyVerb(item("a", { custody: "held", owner: "@julia" }), "release", {
      actor: "julia",
      now: stamp,
      note: "handing to @risk",
    });
    expect(patch).toMatchObject({
      custody: "released",
      owner: null,
      custody_note: "handing to @risk",
      custody_note_by: "julia",
    });
  });

  it("blocking names the blocker rather than writing the word", () => {
    const patch = applyVerb(item("a", { status: "open" }), "block", {
      actor: "julia",
      now: stamp,
      blockedBy: "#502",
    });
    expect(patch.blocked_by).toBe("#502");
    expect(patch.status).toBeUndefined();
  });

  it("promote drops the row off the live board without inventing a back-link", () => {
    const patch = applyVerb(item("a", { status: "open" }), "promote", { actor: "julia", now: "t" });
    expect(patch).toMatchObject({ status: "resolved", promoted: true });
    expect(patch.issue).toBeUndefined();
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

  it("infers the type the contract names for every case, as the CLI must too", () => {
    const schemaContract = (contract as unknown as {
      schema: { cases: { name: string; values: unknown[]; type: string }[]; types: string[]; max_select_cardinality: number };
    }).schema;
    for (const c of schemaContract.cases) {
      const rows = c.values.map((v, i) => item(`r${i}`, { [c.name]: v }));
      const found = inferSchema(rows).find(f => f.name === c.name);
      expect(`${c.name}: ${found?.type}`).toBe(`${c.name}: ${c.type}`);
      expect(schemaContract.types).toContain(found?.type);
    }
  });

  it("sorts an out-of-vocabulary option last, the way the CLI does", () => {
    // A field with a known vocabulary can still hold a value outside it: the
    // room wrote `flaky` where the board knows green/running/red. It is a select
    // by the discovered path, and the stray value belongs after the known ones,
    // not before them, which is where `indexOf` used to put it.
    const rows = [item("a", { ci: "green" }), item("b", { ci: "green" }), item("c", { ci: "flaky" })];
    const options = inferSchema(rows).find(f => f.name === "ci")?.options ?? [];
    expect(options.map(o => o.value)).toEqual(["green", "running", "red", "flaky"]);
  });

  it("uses the contracted upstream field and states", () => {
    const upstream = (contract as unknown as { upstream: { field: string; states: string[] } }).upstream;
    expect([...UPSTREAM_STATES]).toEqual(upstream.states);
    // Neither of the row's own fields: `status` is the row's lifecycle and
    // `live` is a boolean for agent presence.
    expect(["status", "live"]).not.toContain(upstream.field);
  });

  it("writes exactly the upstream fields the contract names", () => {
    // Asserted against what the code writes, not against a copy of it: the
    // companion list drifted the moment two fields were added without touching
    // it, because nothing recomputed it.
    const upstream = (contract as unknown as { upstream: { field: string; companion_fields: string[] } }).upstream;
    const rows: LiveItem[] = ["resolved", "pending", "two-refs", "errored"].map(id => ({
      id, title: id, source: { kind: "memory", label: id }, fields: {},
    }));
    const out = attachUpstream(rows, {
      room: "atlas", field: "upstream", providers: ["github"], refreshing: false,
      refs: [
        { ref: "a", provider: "github", kind: "pull_request", id: "o/r#1", url: "https://x", freshness: "fresh", state: "ok", label: "approved", age_seconds: 30, error: null, origins: [] },
        { ref: "b", provider: "github", kind: "pull_request", id: "o/r#2", url: null, freshness: "missing", state: null, label: null, age_seconds: null, error: null, origins: [] },
        { ref: "c", provider: "github", kind: "pull_request", id: "o/r#3", url: null, freshness: "fresh", state: "failed", label: "CI failing", age_seconds: 30, error: null, origins: [] },
        { ref: "d", provider: "github", kind: "pull_request", id: "o/r#4", url: null, freshness: "error", state: "unknown", label: null, age_seconds: 30, error: "not visible to this token", origins: [] },
      ],
      rows: { resolved: ["a"], pending: ["b"], "two-refs": ["a", "c"], errored: ["d"] },
    });
    const written = new Set(out.flatMap(r => Object.keys(r.fields)));
    expect([...written].sort()).toEqual([upstream.field, ...upstream.companion_fields].sort());
  });

  it("folds a thread onto a row under exactly the contracted field names", () => {
    const unit = (contract as unknown as {
      unit: { binding_field: string; thread_fields: string[]; unit_fields: string[]; thread_states: string[] };
    }).unit;
    expect(EPISODE_FIELD).toBe(unit.binding_field);
    expect(THREAD_FIELDS).toEqual(unit.thread_fields);
    expect(THREAD_STATES).toEqual(unit.thread_states);
    expect(UNIT_FIELDS).toEqual(unit.unit_fields);
  });

  it("never lets a thread write one of the unit's own axes", () => {
    // The container-outlives-the-negotiation rule, asserted as a disjointness
    // rather than as a promise in a comment.
    const unit = (contract as unknown as { unit: { thread_fields: string[]; unit_fields: string[] } }).unit;
    expect(unit.thread_fields.filter(f => unit.unit_fields.includes(f))).toEqual([]);
  });

  it("keeps the log's calendar conventions the CLI also asserts", () => {
    const log = (contract as unknown as { log: { week_starts_on: string; daily_goal: number; heat_thresholds: number[] } }).log;
    expect(log.week_starts_on).toBe("monday");
    expect(DAILY_GOAL).toBe(log.daily_goal);
    // Monday is column zero, and each threshold is the last count at its level.
    expect(weekdayIndex("2026-08-17")).toBe(0);
    log.heat_thresholds.forEach((bound, level) => expect(heatLevel(bound)).toBe(level));
    expect(heatLevel(log.heat_thresholds[log.heat_thresholds.length - 1] + 1)).toBe(log.heat_thresholds.length);
  });

  it("offers the contracted status vocabulary as select options", () => {
    const schema = inferSchema([item("a", { status: "open" })]);
    expect(schema.find(f => f.name === "status")?.options.map(o => o.value)).toEqual(contract.statuses);
  });
});


describe("upstream answers on rows", () => {
  const row = (id: string, fields: Record<string, unknown> = {}): LiveItem => ({
    id,
    title: id,
    source: { kind: "memory", label: id },
    fields,
  });

  const status = (refs: Partial<RoomStatus["refs"][number]>[], rows: Record<string, string[]>): RoomStatus => ({
    room: "atlas",
    field: "upstream",
    providers: ["github"],
    refs: refs.map(r => ({
      ref: r.ref ?? "x", provider: "github", kind: "pull_request", id: r.id ?? "o/r#1",
      url: r.url ?? null, freshness: r.freshness ?? "fresh",
      // `??` would swallow an explicit null, which is exactly the case these
      // cover: a reference the hub has no answer for yet.
      state: r.state === undefined ? "ok" : r.state,
      label: r.label ?? null, age_seconds: r.age_seconds ?? 0, error: r.error ?? null,
      origins: r.origins ?? [],
    })),
    rows,
    refreshing: false,
  });

  it("lands an answer on the row that mentioned it", () => {
    const [out] = attachUpstream(
      [row("memory:work/cutover")],
      status([{ ref: "a", state: "blocked", label: "changes requested" }], { "memory:work/cutover": ["a"] }),
    );
    expect(out.fields.upstream).toBe("blocked");
    expect(out.fields.upstream_label).toBe("changes requested");
  });

  it("shows the worse of two references and says there were more", () => {
    const [out] = attachUpstream(
      [row("memory:work/cutover")],
      status(
        [{ ref: "a", state: "ok", label: "approved" }, { ref: "b", state: "failed", label: "CI failing" }],
        { "memory:work/cutover": ["a", "b"] },
      ),
    );
    // A board says what needs a person, so the failing one wins.
    expect(out.fields.upstream).toBe("failed");
    expect(out.fields.upstream_count).toBe(2);
  });

  it("leaves a row nothing was found for completely untouched", () => {
    const original = row("memory:work/other", { status: "open" });
    const [out] = attachUpstream([original], status([{ ref: "a" }], { "memory:work/cutover": ["a"] }));
    expect(out).toBe(original);
    expect(out.fields).not.toHaveProperty("upstream");
  });

  it("shows the reason when an answer errored rather than an empty label", () => {
    const [out] = attachUpstream(
      [row("memory:work/cutover")],
      status([{ ref: "a", state: "unknown", label: null, error: "not visible to this token" }], { "memory:work/cutover": ["a"] }),
    );
    expect(out.fields.upstream_label).toBe("not visible to this token");
  });

  it("marks a row whose answer has not come back yet as pending, not unknown", () => {
    const [out] = attachUpstream(
      [row("memory:work/cutover")],
      { ...status([{ ref: "a", state: null, label: null, freshness: "missing" }], { "memory:work/cutover": ["a"] }), refreshing: true },
    );
    // `unknown` is a provider saying it could not place what it found; this is
    // nobody having answered yet. A board grouping by upstream must not collect
    // a bucket of rows that were merely early.
    expect(out.fields).not.toHaveProperty("upstream");
    expect(out.fields.upstream_pending).toBe(true);
  });

  it("shows what is known on a row where one answer landed and another has not", () => {
    const [out] = attachUpstream(
      [row("memory:work/cutover")],
      status(
        [
          { ref: "a", state: null, freshness: "missing" },
          { ref: "b", state: "blocked", label: "changes requested" },
        ],
        { "memory:work/cutover": ["a", "b"] },
      ),
    );
    expect(out.fields.upstream).toBe("blocked");
  });

  it("keeps a stale value and says it is stale rather than hiding it", () => {
    const [out] = attachUpstream(
      [row("memory:work/cutover")],
      status([{ ref: "a", state: "ok", label: "approved", freshness: "stale", age_seconds: 5400 }], { "memory:work/cutover": ["a"] }),
    );
    // The truth as far as anyone knows, with a refresh behind it. Taking the
    // value away would tell the reader less, not more.
    expect(out.fields.upstream).toBe("ok");
    expect(out.fields.upstream_freshness).toBe("stale");
    expect(out.fields.upstream_age).toBe("1h ago");
  });

  it("reads an answer's age the way the rest of the board reads ages", () => {
    expect(upstreamAge(30)).toBe("just now");
    expect(upstreamAge(600)).toBe("10m ago");
    expect(upstreamAge(7200)).toBe("2h ago");
    expect(upstreamAge(null)).toBeNull();
  });

  it("types upstream as a select the board can group by", () => {
    const schema = inferSchema([row("a", { upstream: "ok" }), row("b", { upstream: "failed" })]);
    expect(schema.find(f => f.name === "upstream")?.type).toBe("select");
    expect(groupableFields(schema).map(f => f.name)).toContain("upstream");
  });
});


describe("the no-value column is not a value", () => {
  const row = (id: string, fields: Record<string, unknown> = {}): LiveItem => ({
    id, title: id, source: { kind: "memory", label: id }, fields,
  });

  it("collects rows with an empty field under a key the field could never hold", () => {
    const rows = [row("a", { owner: "@julia" }), row("b")];
    const groups = groupItems(rows, { ...DEFAULT_VIEW, groupBy: "owner" }, inferSchema(rows));
    const empty = groups.find(g => g.items.some(i => i.id === "b"));
    expect(empty?.key).toBe(UNGROUPED);
    // A NUL-prefixed sentinel cannot collide with a real frontmatter value, so
    // dropping onto this column is always distinguishable from a real move.
    expect(UNGROUPED.startsWith("\u0000")).toBe(true);
    expect(empty?.label).toBe("No owner");
  });
});
