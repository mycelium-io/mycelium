// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The verbs a scripted scenario plays a room with: the writes the hub would
 * make when an agent speaks, joins, files, claims or resolves, each stored on
 * the room's fixture (so a refetch finds it) and put on its stream (so the
 * app draws it at once). The demo (`demo.ts`) and the Learn takes (`learn.ts`)
 * are both directors over these.
 */

import type { RoomFloor } from "@/lib/api";
import type { MockMemory, MockMessage, RoomFixture } from "./fixtures";
import { liveEpisode, memoryChangedFrame, noticeFrame, pingFrame, publish, respondingFrame } from "./live";

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
export const nowIso = (): string => new Date().toISOString();

/** Acts already played, so a second summon or a refetch never replays one. */
const g = globalThis as typeof globalThis & { __myceliumDirectorActs?: Set<string> };
const played: Set<string> = (g.__myceliumDirectorActs ??= new Set());

/** True the first time `act` is asked for in this server's life. */
export function once(act: string): boolean {
  if (played.has(act)) return false;
  played.add(act);
  return true;
}

let seq = 0;

export class Director {
  readonly live: string;

  /** `pace` stretches every `think`, so a take can give a reader time to read. */
  constructor(
    readonly room: string,
    readonly fx: RoomFixture,
    readonly pace = 1,
  ) {
    this.live = liveEpisode(room);
  }

  /** A thread's episode URN, from its short id. */
  ep(short: string): string {
    return `urn:ioc:mycelium:episode:${this.room}:${short}`;
  }

  /** Post a message as `who`, in `episode` (a thread) or the room. */
  say(who: string, content: string, episode: string | null = null, conductor?: Record<string, unknown>): MockMessage {
    const msg: MockMessage = {
      id: `${this.room}-${++seq}`,
      sender_handle: who,
      message_type: "broadcast",
      content,
      created_at: nowIso(),
      episode,
      ...(conductor ? { metadata: { conductor } } : {}),
    };
    this.fx.messages.push(msg);
    publish(this.room, { ...msg, room_name: this.room });
    if (episode && episode !== this.live) {
      publish(this.room, pingFrame(this.room, { episode, sender: who, message: msg.id }));
    }
    return msg;
  }

  /** A member joining the room, or a negotiation in it. */
  join(handle: string, intent: string, episode: string = this.live): void {
    const msg: MockMessage = {
      id: `join-${episode}-${handle}`,
      sender_handle: handle,
      message_type: "coordination_join",
      content: JSON.stringify({ handle, intent, episode }),
      created_at: nowIso(),
      episode,
    };
    this.fx.messages.push(msg);
    publish(this.room, { ...msg, room_name: this.room });
  }

  /** An agent visibly working on a reply, for `ms`. */
  async think(who: string, episode: string | null, ms: number): Promise<void> {
    publish(this.room, respondingFrame(who, episode));
    await sleep(ms * this.pace);
  }

  /** A board notice: on the stream, and in the replay a reload reads back. */
  notice(data: Parameters<typeof noticeFrame>[1]): void {
    const frame = { ...noticeFrame(this.room, data), created_at: nowIso() };
    (this.fx.wire ??= []).push(frame);
    publish(this.room, frame);
  }

  /** Write a memory (a note, a decision's record), as `memory set` would. */
  setMemory(key: string, value: string, by: string, meta?: Record<string, unknown>): MockMemory {
    const at = this.fx.memories.find((m) => m.key === key);
    if (at) {
      Object.assign(at, { value, content_text: value, updated_by: by, updated_at: nowIso(), version: at.version + 1 });
      if (meta) at.meta = { ...(at.meta ?? {}), ...meta };
      publish(this.room, memoryChangedFrame(key, at.version, by));
      return at;
    }
    const mem: MockMemory = {
      key,
      value,
      content_text: value,
      meta: meta ?? null,
      created_by: by,
      updated_by: by,
      version: 1,
      updated_at: nowIso(),
    };
    this.fx.memories.push(mem);
    publish(this.room, memoryChangedFrame(key, 1, by));
    return mem;
  }

  /** Merge into a row's frontmatter, as a board action or an agent's write would. */
  patchRow(key: string, meta: Record<string, unknown>, by: string): MockMemory | undefined {
    const row = this.fx.memories.find((m) => m.key === key);
    if (!row) return undefined;
    row.meta = { ...(row.meta ?? {}), ...meta };
    row.version += 1;
    row.updated_at = nowIso();
    row.updated_by = by;
    publish(this.room, memoryChangedFrame(key, row.version, by));
    return row;
  }

  /** File a row with a thread of its own, and say so on the channel. */
  fileRow(key: string, title: string, meta: Record<string, unknown>, by: string, short: string, body?: string): MockMemory {
    const row: MockMemory = {
      key,
      value: body ?? title,
      content_text: body ?? title,
      meta,
      created_by: by,
      updated_by: by,
      version: 1,
      updated_at: nowIso(),
      episode: this.ep(short),
    };
    this.fx.memories.push(row);
    publish(this.room, memoryChangedFrame(key, 1, by));
    this.notice({
      subkind: "filed",
      key,
      title,
      episode: row.episode,
      by,
      kind: String(meta.kind ?? "action"),
      for: typeof meta.assignee === "string" ? meta.assignee : undefined,
    });
    return row;
  }

  claim(key: string, who: string): void {
    const row = this.patchRow(key, { assignment: "held", owner: `@${who}`, claimed_at: nowIso(), ttl_minutes: 120 }, who);
    if (row) this.notice({ subkind: "claimed", key, title: titleOf(row), episode: row.episode, by: who });
  }

  resolve(key: string, who: string, extra: Record<string, unknown> = {}): void {
    const row = this.patchRow(key, { assignment: "resolved", status: "resolved", ...extra }, who);
    if (row) this.notice({ subkind: "resolved", key, title: titleOf(row), episode: row.episode, by: who });
  }

  /** Who is present, and what they're on. */
  present(handle: string, title?: string): void {
    this.fx.presence = (this.fx.presence ?? []).filter((p) => p.handle !== handle);
    this.fx.presence.push({ handle, kind: "lease", last_seen: nowIso(), ...(title ? { title } : {}) });
  }

  /** Hold a thread's floor for someone, or release it (`null`). */
  floor(floor: RoomFloor | null, episode: string, by = "conductor"): void {
    const held = (this.fx.floors ?? []).find((f) => f.episode === episode);
    this.fx.floors = (this.fx.floors ?? []).filter((f) => f.episode !== episode);
    if (floor) this.fx.floors.push(floor);
    const key = floor?.key ?? held?.key;
    if (!key) return;
    this.notice({
      subkind: "floor",
      key,
      title: (floor ?? held)?.title ?? undefined,
      episode,
      by,
      ...(floor ? { speakers: floor.speakers.join(",") } : { released: "1" }),
    });
    // The members read carries the floors; a write is what makes the app refetch it.
    const row = this.fx.memories.find((m) => m.key === key);
    if (row) publish(this.room, memoryChangedFrame(key, row.version, by));
  }

  /** The row a thread belongs to. */
  rowOf(episode: string | null | undefined): MockMemory | undefined {
    return episode ? this.fx.memories.find((m) => m.episode === episode) : undefined;
  }

  /** The row whose title starts with `prefix`. */
  rowTitled(prefix: string): MockMemory | undefined {
    return this.fx.memories.find((m) => m.episode && titleOf(m).startsWith(prefix));
  }
}

export function titleOf(m: MockMemory): string {
  const text = typeof m.value === "string" ? m.value : (m.content_text ?? "");
  return text.split("\n")[0];
}
