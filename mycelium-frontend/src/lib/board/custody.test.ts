// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Custody: the board's claims, held as leases rather than as facts.
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
  CUSTODY_COMPANION_FIELDS,
  CUSTODY_REFUSALS,
  CUSTODY_STATES,
  DEFAULT_TTL_MINUTES,
  DERIVED_CUSTODY_STATES,
  LEASABLE_NAMESPACES,
  LENS_OF_CUSTODY,
  RUNTIME_AUTHOR,
  STALE_AFTER,
  STORED_CUSTODY_STATES,
  claimPatch,
  custodyNote,
  custodyOf,
  custodyRefusal,
  isBlocked,
  leaseFreshness,
  releasePatch,
  remainingMinutes,
} from "@/lib/board/custody";
import { lensOf, type LiveItem, type SourceKind } from "@/lib/board/item";
import { projectItems } from "@/lib/board/projection";
import type { AgentSummary, Memory, PresenceMember } from "@/lib/api";

const CONTRACT = JSON.parse(
  readFileSync(join(process.cwd(), "..", "contracts", "board-vocabulary.json"), "utf8"),
).custody;

const NOW = Date.parse("2026-08-23T12:00:00Z");

const ago = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();

const row = (
  fields: Record<string, unknown>,
  kind: SourceKind = "memory",
  label = "work/auth-spike",
): LiveItem => ({ id: `${kind}:${label}`, title: label, source: { kind, label }, fields });

const held = (minutesAgo: number, extra: Record<string, unknown> = {}) =>
  row({ custody: "held", owner: "@growth", claimed_at: ago(minutesAgo), ttl_minutes: 30, ...extra });

describe("the custody contract", () => {
  it("matches the states the CLI and the backend carry", () => {
    expect(CONTRACT.states).toEqual([...CUSTODY_STATES]);
    expect(CONTRACT.stored_states).toEqual(STORED_CUSTODY_STATES);
    expect(CONTRACT.derived_states).toEqual(DERIVED_CUSTODY_STATES);
  });

  it("keeps the stored and derived halves disjoint and exhaustive", () => {
    // A state that is both stored and derived would let a writer freeze a row in
    // the one state the clock is supposed to own.
    const overlap = STORED_CUSTODY_STATES.filter(s => DERIVED_CUSTODY_STATES.includes(s));
    expect(overlap).toEqual([]);
    expect([...STORED_CUSTODY_STATES, ...DERIVED_CUSTODY_STATES].sort()).toEqual(
      [...CUSTODY_STATES].sort(),
    );
  });

  it("matches the thresholds, fields and refusals", () => {
    expect(CONTRACT.stale_after).toBe(STALE_AFTER);
    expect(CONTRACT.default_ttl_minutes).toBe(DEFAULT_TTL_MINUTES);
    expect(CONTRACT.companion_fields).toEqual(CUSTODY_COMPANION_FIELDS);
    expect(CONTRACT.runtime_author).toBe(RUNTIME_AUTHOR);
    expect(CONTRACT.leasable_namespaces).toEqual(LEASABLE_NAMESPACES);
    expect(CONTRACT.blocked_field).toBe(BLOCKED_FIELD);
    expect(CONTRACT.refusals).toEqual(CUSTODY_REFUSALS);
    expect(CONTRACT.lens_of_custody).toEqual(LENS_OF_CUSTODY);
  });

  it("writes only fields the contract names", () => {
    const patch = claimPatch("growth", new Date(NOW).toISOString());
    const written = Object.keys(patch).filter(k => k !== "owner" && k !== "custody");
    expect(written.every(k => CUSTODY_COMPANION_FIELDS.includes(k))).toBe(true);
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

describe("custody state", () => {
  it("holds while the lease runs, stale included", () => {
    // Stale is a renewal being due, not a lease being over: taking the row away
    // the moment a heartbeat is late would thrash.
    expect(custodyOf(held(1), NOW)).toBe("held");
    expect(custodyOf(held(20), NOW)).toBe("held");
  });

  it("expires a claim nobody renewed, with nothing written down", () => {
    const item = held(90);
    expect(item.fields.custody).toBe("held");
    expect(custodyOf(item, NOW)).toBe("expired");
  });

  it("treats held-by-nobody as back in the pool", () => {
    expect(custodyOf(row({ custody: "held", claimed_at: ago(1) }), NOW)).toBe("unclaimed");
  });

  it("refuses a claim it cannot date or bound", () => {
    // "Held forever, on nobody's word" is exactly the assertion an actor that can
    // vanish is not entitled to make.
    expect(custodyOf(row({ custody: "held", owner: "@growth", ttl_minutes: 30 }), NOW)).toBe(
      "expired",
    );
    expect(custodyOf(row({ custody: "held", owner: "@growth", claimed_at: ago(1) }), NOW)).toBe(
      "expired",
    );
  });

  it("has no custody axis at all for a row nobody holds that kind of way", () => {
    expect(custodyOf(row({ status: "resolved" }), NOW)).toBeNull();
    expect(custodyOf(row({ custody: "in_progress" }), NOW)).toBeNull();
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
    const item = row({ custody: "released", custody_note: "handing over", custody_note_by: "growth" });
    expect(custodyNote(item, NOW)).toEqual({ text: "handing over", by: "growth" });
  });

  it("signs an expiry with the runtime, because nobody was there to sign it", () => {
    const note = custodyNote(held(90), NOW);
    expect(note?.by).toBe(RUNTIME_AUTHOR);
    expect(note?.text).toContain("stopped renewing");
  });

  it("lets a reader tell a handoff from an abandonment", () => {
    // They leave the same row behind — an unclaimed one with history. The byline
    // is the whole difference.
    const handed = row({ custody: "released", custody_note: "done", custody_note_by: "growth" });
    expect(custodyNote(handed, NOW)?.by).not.toBe(custodyNote(held(90), NOW)?.by);
    expect(lensOf(handed, NOW)).toBe(lensOf(held(90), NOW));
  });
});

describe("refusals", () => {
  it("tells a plan task, an episode and a presence row why not", () => {
    expect(custodyRefusal(row({}, "plan", "t3"))).toBe(CUSTODY_REFUSALS.plan);
    expect(custodyRefusal(row({}, "episode", "e4f1"))).toBe(CUSTODY_REFUSALS.episode);
    expect(custodyRefusal(row({}, "agent", "growth"))).toBe(CUSTODY_REFUSALS.agent);
  });

  it("takes a lease on a work/ memory and nowhere else", () => {
    expect(custodyRefusal(row({ namespace: "work" }, "memory", "work/auth"))).toBeNull();
    expect(custodyRefusal(row({ namespace: "status" }, "memory", "status/ci"))).not.toBeNull();
  });
});

describe("patches", () => {
  it("stamps a holder, a time and a window", () => {
    expect(claimPatch("growth", new Date(NOW).toISOString(), 45)).toEqual({
      custody: "held",
      owner: "@growth",
      claimed_at: new Date(NOW).toISOString(),
      ttl_minutes: 45,
      custody_note: null,
      custody_note_by: null,
    });
  });

  it("clears the holder on release and records who let go", () => {
    const patch = releasePatch("@growth", new Date(NOW).toISOString(), "blocked on infra");
    expect(patch).toMatchObject({
      custody: "released",
      owner: null,
      claimed_at: null,
      custody_note: "blocked on infra",
      custody_note_by: "growth",
    });
  });
});

describe("the projection, once custody is the axis", () => {
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
      plan: null,
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
    expect(item.fields.custody).toBe("unclaimed");
    expect(item.fields.owner).toBeNull();
    expect(item.fields.writer).toBe("@julia");
  });

  it("reads a claim out of the memory's own frontmatter", () => {
    const [item] = project({
      memories: [
        memory("work/auth-spike", {
          custody: "held",
          owner: "@growth",
          claimed_at: ago(3),
          ttl_minutes: 30,
        }),
      ],
    });
    expect(custodyOf(item, NOW)).toBe("held");
    expect(lensOf(item, NOW)).toBe("in_flight");
  });

  it("gives a custody axis only to the namespace that can hold one", () => {
    const items = project({ memories: [memory("status/ci"), memory("work/auth")] });
    const byId = Object.fromEntries(items.map(i => [i.id, i]));
    expect(byId["memory:status/ci"].fields.custody).toBeUndefined();
    expect(byId["memory:work/auth"].fields.custody).toBe("unclaimed");
  });

  it("dates a resident agent's row from its last poll", () => {
    const [item] = project({
      agents: [agent("growth")],
      presence: new Map([["growth", seen("growth", 2)]]),
    });
    expect(custodyOf(item, NOW)).toBe("held");
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
          custody: "held",
          owner: "@growth",
          claimed_at: ago(90),
          ttl_minutes: 30,
        }),
      ],
    });
    // Nobody touched the row. It drained.
    expect(custodyOf(item, NOW)).toBe("expired");
    expect(lensOf(item, NOW)).toBe("needs_you");
  });
});
