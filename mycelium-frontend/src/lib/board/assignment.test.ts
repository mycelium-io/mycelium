// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Assignment: the board's claims, held as leases rather than as facts.
 *
 * The property under test throughout is the one an ephemeral actor forces:
 * nobody gets to announce that they died, so a claim has to stop being true on
 * its own. A board where every agent went quiet an hour ago must read empty.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  BLOCKED_FIELD,
  ASSIGNMENT_COMPANION_FIELDS,
  ASSIGNMENT_REFUSALS,
  ASSIGNMENT_STATES,
  DEFAULT_TTL_MINUTES,
  DERIVED_ASSIGNMENT_STATES,
  ASSIGNABLE_NAMESPACES,
  ATTENTION_OF_ASSIGNMENT,
  RUNTIME_AUTHOR,
  STALE_AFTER,
  STORED_ASSIGNMENT_STATES,
  claimPatch,
  assignmentNote,
  assignmentOf,
  assignmentRefusal,
  isBlocked,
  leaseFreshness,
  releasePatch,
  remainingMinutes,
} from "@/lib/board/assignment";
import { attentionFilterOf, type LiveItem, type SourceKind } from "@/lib/board/item";
import { projectItems } from "@/lib/board/projection";
import { DEPENDENCY_RELATION, SETTLED_STATUSES, WAITING_FIELD, waitingOnRows } from "@/lib/board/assignment";
import { waitingOn } from "@/lib/board/view";
import type { AgentSummary, Memory, PresenceMember } from "@/lib/api";

const CONTRACT = JSON.parse(
  readFileSync(join(process.cwd(), "..", "contracts", "board-vocabulary.json"), "utf8"),
).assignment;

const NOW = Date.parse("2026-08-23T12:00:00Z");

const ago = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();

const row = (
  fields: Record<string, unknown>,
  kind: SourceKind = "memory",
  label = "work/auth-spike",
): LiveItem => ({ id: `${kind}:${label}`, title: label, source: { kind, label }, fields });

const held = (minutesAgo: number, extra: Record<string, unknown> = {}) =>
  row({ assignment: "held", owner: "@growth", claimed_at: ago(minutesAgo), ttl_minutes: 30, ...extra });

describe("the assignment contract", () => {
  it("matches the states the CLI and the backend carry", () => {
    expect(CONTRACT.states).toEqual([...ASSIGNMENT_STATES]);
    expect(CONTRACT.stored_states).toEqual(STORED_ASSIGNMENT_STATES);
    expect(CONTRACT.derived_states).toEqual(DERIVED_ASSIGNMENT_STATES);
  });

  it("keeps the stored and derived halves disjoint and exhaustive", () => {
    // A state that is both stored and derived would let a writer freeze a row in
    // the one state the clock is supposed to own.
    const overlap = STORED_ASSIGNMENT_STATES.filter(s => DERIVED_ASSIGNMENT_STATES.includes(s));
    expect(overlap).toEqual([]);
    expect([...STORED_ASSIGNMENT_STATES, ...DERIVED_ASSIGNMENT_STATES].sort()).toEqual(
      [...ASSIGNMENT_STATES].sort(),
    );
  });

  it("matches the thresholds, fields and refusals", () => {
    expect(CONTRACT.stale_after).toBe(STALE_AFTER);
    expect(CONTRACT.default_ttl_minutes).toBe(DEFAULT_TTL_MINUTES);
    expect(CONTRACT.companion_fields).toEqual(ASSIGNMENT_COMPANION_FIELDS);
    expect(CONTRACT.runtime_author).toBe(RUNTIME_AUTHOR);
    expect(CONTRACT.assignable_namespaces).toEqual(ASSIGNABLE_NAMESPACES);
    expect(CONTRACT.blocked_field).toBe(BLOCKED_FIELD);
    expect(CONTRACT.refusals).toEqual(ASSIGNMENT_REFUSALS);
    expect(CONTRACT.attention_of_assignment).toEqual(ATTENTION_OF_ASSIGNMENT);
  });

  it("writes only fields the contract names", () => {
    const patch = claimPatch("growth", new Date(NOW).toISOString());
    const written = Object.keys(patch).filter(k => k !== "owner" && k !== "assignment");
    expect(written.every(k => ASSIGNMENT_COMPANION_FIELDS.includes(k))).toBe(true);
  });
});

describe("freshness", () => {
  it("ages fresh, then stale, then expired — the upstream half's words", () => {
    expect(leaseFreshness(held(1), NOW)).toBe("fresh");
    expect(leaseFreshness(held(20), NOW)).toBe("stale");
    expect(leaseFreshness(held(45), NOW)).toBe("expired");
  });

  it("has nothing to report for a row that cannot expire", () => {
    expect(leaseFreshness(row({ status: "open" }), NOW)).toBeNull();
  });

  it("counts the minutes left down to zero", () => {
    expect(remainingMinutes(held(10), NOW)).toBe(20);
    expect(remainingMinutes(held(90), NOW)).toBe(0);
    expect(remainingMinutes(row({ status: "open" }), NOW)).toBeNull();
  });
});

describe("assignment state", () => {
  it("holds while the lease runs, stale included", () => {
    // Stale is a renewal being due, not a lease being over: taking the row away
    // the moment a heartbeat is late would thrash.
    expect(assignmentOf(held(1), NOW)).toBe("held");
    expect(assignmentOf(held(20), NOW)).toBe("held");
  });

  it("expires a claim nobody renewed, with nothing written down", () => {
    const item = held(90);
    expect(item.fields.assignment).toBe("held");
    expect(assignmentOf(item, NOW)).toBe("expired");
  });

  it("treats held-by-nobody as back in the pool", () => {
    expect(assignmentOf(row({ assignment: "held", claimed_at: ago(1) }), NOW)).toBe("unclaimed");
  });

  it("refuses a claim it cannot date or bound", () => {
    // "Held forever, on nobody's word" is exactly the assertion an actor that can
    // vanish is not entitled to make.
    expect(assignmentOf(row({ assignment: "held", owner: "@growth", ttl_minutes: 30 }), NOW)).toBe(
      "expired",
    );
    expect(assignmentOf(row({ assignment: "held", owner: "@growth", claimed_at: ago(1) }), NOW)).toBe(
      "expired",
    );
  });

  it("has no assignment axis at all for a row nobody holds that kind of way", () => {
    expect(assignmentOf(row({ status: "resolved" }), NOW)).toBeNull();
    expect(assignmentOf(row({ assignment: "in_progress" }), NOW)).toBeNull();
  });
});

describe("blocked is derived", () => {
  it("is blocked because it names a blocker", () => {
    expect(isBlocked(row({ blocked_by: ["#502"] }))).toBe(true);
    expect(isBlocked(row({ blocked_by: "#502" }))).toBe(true);
    expect(isBlocked(row({ blocked_by: [] }))).toBe(false);
  });

  it("is not blocked because someone typed the word", () => {
    expect(isBlocked(row({ status: "blocked" }))).toBe(false);
  });
});

describe("notes", () => {
  it("signs a release with the releaser's handle", () => {
    const item = row({ assignment: "released", assignment_note: "handing over", assignment_note_by: "growth" });
    expect(assignmentNote(item, NOW)).toEqual({ text: "handing over", by: "growth" });
  });

  it("signs an expiry with the runtime, because nobody was there to sign it", () => {
    const note = assignmentNote(held(90), NOW);
    expect(note?.by).toBe(RUNTIME_AUTHOR);
    expect(note?.text).toContain("stopped renewing");
  });

  it("lets a reader tell a handoff from an abandonment", () => {
    // They leave the same row behind — an unclaimed one with history. The byline
    // is the whole difference.
    const handed = row({ assignment: "released", assignment_note: "done", assignment_note_by: "growth" });
    expect(assignmentNote(handed, NOW)?.by).not.toBe(assignmentNote(held(90), NOW)?.by);
    expect(attentionFilterOf(handed, NOW)).toBe(attentionFilterOf(held(90), NOW));
  });
});

describe("refusals", () => {
  it("tells an episode and a presence row why not", () => {
    expect(assignmentRefusal(row({}, "episode", "e4f1"))).toBe(ASSIGNMENT_REFUSALS.episode);
    expect(assignmentRefusal(row({}, "agent", "growth"))).toBe(ASSIGNMENT_REFUSALS.agent);
  });

  it("takes a lease on a work/ memory and nowhere else", () => {
    expect(assignmentRefusal(row({ namespace: "work" }, "memory", "work/auth"))).toBeNull();
    expect(assignmentRefusal(row({ namespace: "status" }, "memory", "status/ci"))).not.toBeNull();
  });
});

describe("patches", () => {
  it("stamps a holder, a time and a window", () => {
    expect(claimPatch("growth", new Date(NOW).toISOString(), 45)).toEqual({
      assignment: "held",
      owner: "@growth",
      claimed_at: new Date(NOW).toISOString(),
      ttl_minutes: 45,
      assignment_note: null,
      assignment_note_by: null,
    });
  });

  it("clears the holder on release and records who let go", () => {
    const patch = releasePatch("@growth", new Date(NOW).toISOString(), "blocked on infra");
    expect(patch).toMatchObject({
      assignment: "released",
      owner: null,
      claimed_at: null,
      assignment_note: "blocked on infra",
      assignment_note_by: "growth",
    });
  });
});

describe("the projection, once assignment is the axis", () => {
  const memory = (key: string, meta: Record<string, unknown> = {}): Memory => ({
    key,
    value: "Spike the auth rewrite",
    content_text: "Spike the auth rewrite",
    version: 1,
    created_by: "julia",
    updated_by: "julia",
    updated_at: ago(5),
    meta,
  });

  const project = (over: Partial<Parameters<typeof projectItems>[0]> = {}) =>
    projectItems({
      room: "atlas",
      episodes: [],
      memories: [],
      agents: [],
      presence: new Map(),
      now: new Date(NOW).toISOString(),
      ...over,
    });

  const agent = (handle: string): AgentSummary =>
    ({ handle, adapter: "claude_code" }) as AgentSummary;

  const seen = (handle: string, minutesAgo: number): PresenceMember => ({
    handle,
    kind: "lease",
    last_seen: ago(minutesAgo),
  });

  it("starts a work/ memory unclaimed rather than owned by whoever wrote it", () => {
    // Reading `owner` off `updated_by` gave every memory in the room a holder —
    // the confident lie this axis exists to stop.
    const [item] = project({ memories: [memory("work/auth-spike")] });
    expect(item.fields.assignment).toBe("unclaimed");
    expect(item.fields.owner).toBeNull();
    expect(item.fields.writer).toBe("@julia");
  });

  it("reads a claim out of the memory's own frontmatter", () => {
    const [item] = project({
      memories: [
        memory("work/auth-spike", {
          assignment: "held",
          owner: "@growth",
          claimed_at: ago(3),
          ttl_minutes: 30,
        }),
      ],
    });
    expect(assignmentOf(item, NOW)).toBe("held");
    expect(attentionFilterOf(item, NOW)).toBe("in_flight");
  });

  it("gives a assignment axis only to the namespace that can hold one", () => {
    const items = project({ memories: [memory("status/ci"), memory("work/auth")] });
    const byId = Object.fromEntries(items.map(i => [i.id, i]));
    expect(byId["memory:status/ci"].fields.assignment).toBeUndefined();
    expect(byId["memory:work/auth"].fields.assignment).toBe("unclaimed");
  });

  it("dates a resident agent's row from its last poll", () => {
    const [item] = project({
      agents: [agent("growth")],
      presence: new Map([["growth", seen("growth", 2)]]),
    });
    expect(assignmentOf(item, NOW)).toBe("held");
  });

  it("reads empty when every agent died an hour ago", () => {
    // The test the whole model exists to pass.
    const items = project({
      agents: [agent("growth"), agent("risk")],
      presence: new Map([
        ["growth", seen("growth", 60)],
        ["risk", seen("risk", 75)],
      ]),
    });
    expect(items).toEqual([]);
  });

  it("returns work a dead agent was holding to the pool", () => {
    const [item] = project({
      memories: [
        memory("work/auth-spike", {
          assignment: "held",
          owner: "@growth",
          claimed_at: ago(90),
          ttl_minutes: 30,
        }),
      ],
    });
    // Nobody touched the row. It drained.
    expect(assignmentOf(item, NOW)).toBe("expired");
    expect(attentionFilterOf(item, NOW)).toBe("needs_you");
  });
});

describe("what a row waits on", () => {
  // Read off the other rows and stored nowhere: a dependency resolving changes
  // what its dependents wait on with nobody writing a byte.
  const contract = JSON.parse(
    readFileSync(join(__dirname, "..", "..", "..", "..", "contracts", "board-vocabulary.json"), "utf8"),
  ) as { task: { dependency_relation: string; waiting_field: string; settled_statuses: string[] } };

  const memory = (key: string, meta: Record<string, unknown> = {}): Memory => ({
    key,
    value: "Spike the auth rewrite",
    content_text: "Spike the auth rewrite",
    version: 1,
    created_by: "julia",
    updated_by: "julia",
    updated_at: new Date(NOW).toISOString(),
    meta,
  });

  const project = (...memories: Memory[]) => {
    const rows = projectItems({
      room: "atlas",
      episodes: [],
      memories,
      agents: [],
      presence: new Map(),
      now: new Date(NOW).toISOString(),
    });
    return new Map(rows.map(row => [row.source.label, row]));
  };

  it("uses the contracted words, as the CLI must too", () => {
    expect(DEPENDENCY_RELATION).toBe(contract.task.dependency_relation);
    expect(WAITING_FIELD).toBe(contract.task.waiting_field);
    expect([...SETTLED_STATUSES]).toEqual(contract.task.settled_statuses);
  });

  it("waits on its open dependencies and not its settled ones", () => {
    const rows = project(
      memory("work/schema"),
      memory("work/migrate", { status: "resolved" }),
      memory("work/deploy", { assignment: "resolved" }),
      memory("work/api", { "depends-on": ["work/schema", "work/migrate", "work/deploy"] }),
    );
    expect(waitingOnRows(rows.get("work/api")!)).toEqual(["work/schema"]);
    expect(waitingOn(rows.get("work/api")!)).toBe("after work/schema");
  });

  it("does not wait on a reference", () => {
    const rows = project(memory("work/api", { "depends-on": ["context/design", "work/never-filed"] }));
    expect(waitingOnRows(rows.get("work/api")!)).toEqual([]);
    expect(waitingOn(rows.get("work/api")!)).toBeNull();
  });

  it("carries no column where there is nothing to say", () => {
    const rows = project(memory("work/api"));
    expect(WAITING_FIELD in rows.get("work/api")!.fields).toBe(false);
  });

  it("a named blocker still reads first", () => {
    const rows = project(
      memory("work/schema"),
      memory("work/api", { "depends-on": "work/schema", blocked_by: ["#502"] }),
    );
    expect(waitingOn(rows.get("work/api")!)).toBe("waiting on #502");
  });
});
