// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Unsent messages, kept per room and per task thread in this browser.
 *
 * Switching rooms (or closing a thread) used to throw away whatever was typed.
 * A draft is written as it's typed and read back when that composer shows
 * again, and it goes when the message is sent or the box is emptied. It never
 * leaves this browser: a draft is yours until you send it.
 */

const PREFIX = "mycelium.draft:";

/** Where a composer's draft is kept: the room, and the thread when there is one. */
export function draftKey(room: string, episode: string | null = null): string {
  return `${PREFIX}${room}${episode ? `#${episode}` : ""}`;
}

export function loadDraft(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

export function saveDraft(key: string, text: string): void {
  try {
    if (text.trim()) window.localStorage.setItem(key, text);
    else window.localStorage.removeItem(key);
  } catch {
    // Keeping a draft is a convenience; typing still works without it.
  }
}

const SENT_PREFIX = "mycelium.sent:";
/** How many sent messages a room's composer remembers. */
export const SENT_KEPT = 50;

/**
 * What you've sent in a room from this browser, oldest first: the list Up
 * steps back through in its composer, the way a shell steps through history.
 */
export function loadSent(room: string): string[] {
  try {
    const kept: unknown = JSON.parse(window.localStorage.getItem(`${SENT_PREFIX}${room}`) ?? "[]");
    return Array.isArray(kept) ? kept.filter((t): t is string => typeof t === "string") : [];
  } catch {
    return [];
  }
}

/** Remember a sent message, once even when sent twice in a row. */
export function rememberSent(room: string, text: string): void {
  const body = text.trim();
  if (!body) return;
  const sent = loadSent(room);
  if (sent[sent.length - 1] === body) return;
  try {
    window.localStorage.setItem(`${SENT_PREFIX}${room}`, JSON.stringify([...sent, body].slice(-SENT_KEPT)));
  } catch {
    // Like a draft, history is a convenience.
  }
}
