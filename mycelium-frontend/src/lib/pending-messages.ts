// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Messages you sent that the room has not shown back yet.
 *
 * A send is a POST the hub answers only once it has published the message and
 * run its hooks, and the conversation shows it only after the next read. So the
 * composer draws the message here at once and goes back to being a box to type
 * in, and each conversation draws what is still pending for it below what it
 * has read. An entry goes once the read has it; one the hub refused stays, with
 * its text, until it is sent again or let go.
 *
 * This is client state (nothing the hub owns yet), so it lives in the browser
 * beside the SWR cache rather than in it, and it is gone on reload.
 */

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { sendRoomMessage } from "@/lib/api";

export type PendingState = "sending" | "sent" | "failed";

export interface PendingMessage {
  /** Made here, so a row has a key before the hub has given it an id. */
  id: string;
  room: string;
  /** The thread it was sent into; null for the room itself. */
  episode: string | null;
  sender: string;
  content: string;
  /** When it was drawn (ms since the epoch). */
  at: number;
  state: PendingState;
  /** Why the hub refused it, for a failed one. */
  error: string | null;
  /** The stored message's id, once the POST has answered with it. */
  messageId: string | null;
}

/** A message a conversation has read, as far as matching one up needs. */
export interface Landed {
  id: string | null;
  sender: string;
  content: string;
  /** Its stamp, when it has one. */
  at: string | null;
}

/** How long a sent message may go unseen before it stops being drawn. The read
 *  normally has it within a poll; this only keeps a message the read never
 *  matches from sitting there for good. */
const SENT_TTL_MS = 2 * 60_000;

/** How far the hub's clock may be behind this one and a message still count as
 *  the one just sent rather than an older one with the same words. */
const CLOCK_SLACK_MS = 30_000;

let entries: PendingMessage[] = [];
const listeners = new Set<() => void>();
let counter = 0;

function emit(next: PendingMessage[]): void {
  entries = next;
  for (const listener of listeners) listener();
}

function patch(id: string, change: Partial<PendingMessage>): void {
  if (!entries.some((e) => e.id === id)) return;
  emit(entries.map((e) => (e.id === id ? { ...e, ...change } : e)));
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot(): PendingMessage[] {
  return entries;
}

const NONE: PendingMessage[] = [];

function serverSnapshot(): PendingMessage[] {
  return NONE;
}

async function post(entry: PendingMessage): Promise<boolean> {
  try {
    const stored = await sendRoomMessage(entry.room, {
      sender_handle: entry.sender,
      content: entry.content,
      episode: entry.episode,
    });
    patch(entry.id, { state: "sent", messageId: stored?.id ?? null });
    setTimeout(() => forget(entry.id), SENT_TTL_MS);
    return true;
  } catch (err) {
    patch(entry.id, { state: "failed", error: err instanceof Error ? err.message : String(err) });
    return false;
  }
}

/**
 * Draw a message and send it. Resolves true once the hub has it, false when it
 * refused it; either way the entry says so, so the caller has nothing to show.
 */
export function sendPending(
  room: string,
  message: { sender: string; content: string; episode: string | null },
): Promise<boolean> {
  counter += 1;
  const entry: PendingMessage = {
    id: `pending-${Date.now().toString(36)}-${counter}`,
    room,
    episode: message.episode,
    sender: message.sender,
    content: message.content,
    at: Date.now(),
    state: "sending",
    error: null,
    messageId: null,
  };
  emit([...entries, entry]);
  return post(entry);
}

/** Send a failed one again, where it is. */
export function retryPending(id: string): Promise<boolean> {
  const entry = entries.find((e) => e.id === id);
  if (!entry || entry.state !== "failed") return Promise.resolve(false);
  const again = { ...entry, state: "sending" as const, error: null };
  patch(id, again);
  return post(again);
}

/** Let one go: a failed message you no longer want, or one the read now has. */
export function forget(id: string): void {
  if (!entries.some((e) => e.id === id)) return;
  emit(entries.filter((e) => e.id !== id));
}

/** Empty the store. For tests. */
export function resetPending(): void {
  emit([]);
}

/**
 * Which of `pending` the read already has, by id. Each read message stands for
 * at most one pending one, matched by the id the POST returned, else by sender
 * and text among messages no older than the send, since a copy that came in on
 * the stream carries an id of its own.
 */
export function matchLanded(pending: readonly PendingMessage[], landed: readonly Landed[]): Set<string> {
  const matched = new Set<string>();
  const used = new Set<number>();
  for (const entry of pending) {
    if (entry.state === "failed") continue;
    let found = entry.messageId ? landed.findIndex((m, i) => !used.has(i) && m.id === entry.messageId) : -1;
    if (found === -1) {
      found = landed.findIndex((m, i) => {
        if (used.has(i) || m.sender !== entry.sender || m.content.trim() !== entry.content.trim()) return false;
        const at = m.at ? Date.parse(m.at) : NaN;
        return Number.isNaN(at) || at >= entry.at - CLOCK_SLACK_MS;
      });
    }
    if (found === -1) continue;
    used.add(found);
    matched.add(entry.id);
  }
  return matched;
}

/**
 * What is still pending in one conversation (`episode` null for the room), in
 * the order it was sent. Whatever `landed` already has is dropped from the
 * store, so a later read that pages it out never brings the pending copy back.
 */
export function usePendingMessages(
  room: string,
  episode: string | null,
  landed: readonly Landed[],
): PendingMessage[] {
  const all = useSyncExternalStore(subscribe, snapshot, serverSnapshot);
  const here = useMemo(
    () => all.filter((e) => e.room === room && e.episode === episode),
    [all, room, episode],
  );
  const matched = useMemo(() => matchLanded(here, landed), [here, landed]);
  useEffect(() => {
    for (const id of matched) forget(id);
  }, [matched]);
  return useMemo(() => here.filter((e) => !matched.has(e.id)), [here, matched]);
}
