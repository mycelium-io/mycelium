// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The mock's answer to `GET /rooms/{room}/board` and `/waiting`: the hub's
 * `services/board.py` and `services/waiting.py`, worked out over a fixture.
 *
 * Fixture rows still say who has them with `owner` alone, from before a
 * row's holder was a lease or an assignee, so a mock row's holder reads that
 * too. The fixtures are written at a fixed "now" (`MOCK_NOW`) while the board
 * says how long a task has been quiet against the real clock, so the times
 * these answer are moved up to today.
 */

import type { BoardEpic, BoardPart, BoardRead, LatestLine, PartState, WaitingItem } from "@/lib/api";
import { MOCK_NOW, type MockMemory, type RoomFixture } from "./fixtures";

/** A fixture time, moved up so the fixtures' now is the real one. */
function today(at: string | null | undefined): string | null {
  const ms = Date.parse(at ?? "");
  return Number.isNaN(ms) ? null : new Date(ms + (Date.now() - MOCK_NOW)).toISOString();
}

const BOARD_NAMESPACES = new Set(["decisions", "status", "work", "failed"]);
const SETTLED = new Set(["resolved", "dismissed"]);

const bare = (v: unknown) => (typeof v === "string" ? v.replace(/^@/, "") : "");
const list = (v: unknown): string[] =>
  (Array.isArray(v) ? v : [v]).filter((x): x is string => typeof x === "string" && x.trim() !== "");

function titleOf(m: MockMemory): string {
  const text = typeof m.value === "string" ? m.value : (m.content_text ?? m.key);
  return text.split("\n").find(l => l.trim())?.replace(/^#+\s*/, "").trim() ?? m.key;
}

function firstLine(text: string): string {
  const line = text.split("\n").find(l => l.trim())?.trim() ?? "";
  return line.length > 280 ? `${line.slice(0, 279)}…` : line;
}

class Rows {
  readonly rows = new Map<string, MockMemory>();
  readonly children = new Map<string, string[]>();
  readonly latest = new Map<string, LatestLine>();

  constructor(fx: RoomFixture) {
    for (const m of fx.memories) if (BOARD_NAMESPACES.has(m.key.split("/")[0])) this.rows.set(m.key, m);
    for (const [key, m] of this.rows) {
      const parent = list(m.meta?.["part-of"])[0];
      if (parent && parent !== key && this.rows.has(parent)) {
        this.children.set(parent, [...(this.children.get(parent) ?? []), key]);
      }
    }
    // An engine's post (a conductor's step, a synthesizer's digest) is a report on
    // the thread, not what the work is doing, so it is never a latest line.
    const engines = new Set(
      fx.memories
        .filter(m => m.key.startsWith("agents/") && /adapter:\s*engine/.test(typeof m.value === "string" ? m.value : ""))
        .map(m => m.key.slice("agents/".length)),
    );
    const said = [...fx.messages]
      .filter(m => m.episode && m.content.trim() && ["broadcast", "direct", "reply"].includes(m.message_type))
      .filter(m => !engines.has(m.sender_handle) && !m.metadata?.conductor && m.sender_handle !== "system")
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
    for (const m of said) {
      this.latest.set(m.episode!, { sender: m.sender_handle, text: firstLine(m.content), at: today(m.created_at) });
    }
  }

  meta(key: string): Record<string, unknown> {
    return this.rows.get(key)?.meta ?? {};
  }

  settled(key: string): boolean {
    const meta = this.meta(key);
    return SETTLED.has(String(meta.status)) || meta.assignment === "resolved";
  }

  holder(key: string): string | null {
    const meta = this.meta(key);
    if (meta.assignment === "released" || meta.assignment === "resolved") return null;
    return bare(meta.owner) || bare(meta.assignee) || null;
  }

  waitingOn(key: string): string[] {
    return list(this.meta(key)["depends-on"]).filter(d => d !== key && this.rows.has(d) && !this.settled(d));
  }

  state(key: string): PartState {
    if (this.settled(key)) return "done";
    if (list(this.meta(key).blocked_by).length || key.startsWith("failed/")) return "blocked";
    if (this.waitingOn(key).length) return "waiting";
    return this.holder(key) ? "working" : "open";
  }

  part(key: string): BoardPart {
    const m = this.rows.get(key)!;
    const parts = this.children.get(key) ?? [];
    return {
      key,
      title: titleOf(m),
      episode: m.episode ?? null,
      state: this.state(key),
      holder: this.holder(key),
      assignee: bare(m.meta?.assignee) || null,
      waiting_on: this.waitingOn(key),
      blocked_by: list(m.meta?.blocked_by).join(", ") || null,
      latest: (m.episode && this.latest.get(m.episode)) || null,
      parts: parts.length,
      parts_done: parts.filter(p => this.settled(p)).length,
      updated_at: today(m.updated_at),
    };
  }

  steps(parts: string[]): string[][] {
    const siblings = new Set(parts);
    const depth = new Map<string, number>();
    const visiting = new Set<string>();
    const place = (p: string): number | null => {
      if (depth.has(p)) return depth.get(p)!;
      if (visiting.has(p)) return null;
      visiting.add(p);
      const below = list(this.meta(p)["depends-on"]).filter(d => siblings.has(d) && d !== p).map(place);
      visiting.delete(p);
      if (below.some(b => b === null)) return null;
      const d = 1 + Math.max(-1, ...(below as number[]));
      depth.set(p, d);
      return d;
    };
    parts.forEach(place);
    const last = Math.max(-1, ...depth.values());
    for (const p of parts) if (!depth.has(p)) depth.set(p, last + 1);
    const steps: string[][] = Array.from({ length: Math.max(-1, ...depth.values()) + 1 }, () => []);
    for (const p of parts) steps[depth.get(p)!].push(p);
    return steps;
  }

  lead(key: string): string | null {
    const who = this.holder(key);
    if (who) return who;
    const authors = new Set((this.children.get(key) ?? []).map(p => bare(this.rows.get(p)!.created_by)));
    return authors.size === 1 ? [...authors][0] : null;
  }

  epic(key: string): BoardEpic {
    const parts = this.children.get(key) ?? [];
    return {
      ...this.part(key),
      lead: this.lead(key),
      done: parts.filter(p => this.settled(p)).length,
      total: parts.length,
      steps: this.steps(parts),
      path: parts.map(p => this.part(p)),
    };
  }

  insideOpenEpic(key: string): boolean {
    const parent = list(this.meta(key)["part-of"])[0];
    return !!parent && this.rows.has(parent) && !this.settled(parent);
  }
}

export function mockBoard(fx: RoomFixture): BoardRead {
  const rows = new Rows(fx);
  const read: BoardRead = { epics: [], tasks: [] };
  for (const key of rows.rows.keys()) {
    // Only work is listed on its own; a decision, a failure or a report is read,
    // and shows only as a part of an epic (services/board.py).
    if (!key.startsWith("work/") || rows.settled(key) || rows.insideOpenEpic(key)) continue;
    if (rows.children.get(key)?.length) read.epics.push(rows.epic(key));
    else read.tasks.push(rows.part(key));
  }
  return read;
}

export function mockBoardRow(fx: RoomFixture, key: string): BoardEpic | null {
  const rows = new Rows(fx);
  return rows.rows.has(key) ? rows.epic(key) : null;
}

export function mockWaiting(fx: RoomFixture, handle: string): WaitingItem[] {
  const me = bare(handle);
  const rows = new Rows(fx);
  const byEpisode = new Map([...rows.rows.values()].filter(m => m.episode).map(m => [m.episode!, m.key]));
  const about = (key: string | undefined, episode: string | null) => {
    if (!key) return { key: null, title: null, episode, epic: null, epic_title: null };
    const parent = list(rows.meta(key)["part-of"])[0];
    const epic = parent && rows.rows.has(parent) ? parent : null;
    return {
      key,
      title: titleOf(rows.rows.get(key)!),
      episode,
      epic,
      epic_title: epic ? titleOf(rows.rows.get(epic)!) : null,
    };
  };
  const items: WaitingItem[] = [];
  const seen = new Set<string | null>();
  const answered = new Set<string | null>();
  const pending = new Map<string | null, typeof fx.messages>();
  const mention = new RegExp(`(^|[\\s(<])@!?${me}\\b`, "i");
  // An agent's ask for this member's OK comes first, until it's answered or
  // its task is settled; its thread isn't listed again as a plain ask.
  for (const m of [...fx.messages].sort((a, b) => b.created_at.localeCompare(a.created_at))) {
    const ask = (m.metadata as { ask?: { to?: string; question?: string; answer?: unknown } } | null | undefined)?.ask;
    if (!ask || bare(ask.to ?? "") !== me || ask.answer) continue;
    const thread = m.episode ?? null;
    const key = thread ? byEpisode.get(thread) : undefined;
    if (key && rows.settled(key)) continue;
    items.push({
      kind: "approve",
      ...about(key, thread),
      sender: m.sender_handle,
      text: ask.question ?? m.content,
      message_id: m.id,
      at: today(m.created_at),
      count: 1,
    });
    seen.add(thread);
    answered.add(thread);
  }
  for (const m of [...fx.messages].sort((a, b) => b.created_at.localeCompare(a.created_at))) {
    const thread = m.episode ?? null;
    if (bare(m.sender_handle) === me) {
      answered.add(thread);
      continue;
    }
    if (answered.has(thread) || !mention.test(m.content)) continue;
    const key = thread ? byEpisode.get(thread) : undefined;
    if (key && rows.settled(key)) continue;
    pending.set(thread, [...(pending.get(thread) ?? []), m]);
  }
  for (const [thread, found] of pending) {
    const newest = found[0];
    items.push({
      kind: "ask",
      ...about(thread ? byEpisode.get(thread) : undefined, thread),
      sender: newest.sender_handle,
      // The line that asks this member, else the first (services/waiting.py).
      text: firstLine(newest.content.split("\n").find(l => mention.test(l)) ?? newest.content),
      message_id: newest.id,
      at: today(newest.created_at),
      count: found.length,
    });
    seen.add(thread);
  }
  for (const floor of fx.floors ?? []) {
    if (!floor.speakers.map(bare).includes(me) || seen.has(floor.episode)) continue;
    items.push({
      kind: "turn",
      ...about(byEpisode.get(floor.episode), floor.episode),
      sender: floor.holder,
      text: null,
      message_id: null,
      // The fixtures don't say when a floor was given; the mock says a few
      // minutes ago, as a running flow's turn would be.
      at: today(new Date(MOCK_NOW - 6 * 60_000).toISOString()),
      count: 1,
    });
    seen.add(floor.episode);
  }
  for (const key of rows.rows.keys()) {
    const part = rows.part(key);
    if (part.holder !== me || part.state !== "working" || part.parts > part.parts_done) continue;
    if (part.episode && seen.has(part.episode)) continue;
    items.push({
      kind: "task",
      ...about(key, part.episode ?? null),
      sender: null,
      text: part.latest?.text ?? null,
      message_id: null,
      at: part.updated_at ?? null,
      count: 1,
    });
  }
  return items;
}
