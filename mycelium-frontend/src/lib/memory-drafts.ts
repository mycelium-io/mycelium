// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Unsaved memory edits, kept in this browser so a closed tab, a reload or a
 * link followed mid-edit doesn't lose them. A convenience for one person on
 * one machine, never a store: storage can be missing or full, and every read
 * and write here survives that by doing nothing.
 */

export interface MemoryDraft {
  body: string;
  tags?: string[];
  expandable?: boolean;
  /** A new memory's title and where it was going. */
  title?: string;
  folder?: string;
  name?: string;
  /** The version an edit started from, so a restore can say the memory moved on. */
  baseVersion?: number;
  savedAt: string;
}

const PREFIX = "mycelium:memory-draft:";

/** The draft slot for editing `key` in `room`, or for a new memory there when `key` is null. */
export function draftId(room: string, key: string | null): string {
  return `${PREFIX}${room}:${key ?? "(new)"}`;
}

export function loadDraft(id: string): MemoryDraft | null {
  try {
    const raw = localStorage.getItem(id);
    if (!raw) return null;
    const draft = JSON.parse(raw) as MemoryDraft;
    return typeof draft?.body === "string" ? draft : null;
  } catch {
    return null;
  }
}

export function saveDraft(id: string, draft: Omit<MemoryDraft, "savedAt">): void {
  try {
    localStorage.setItem(id, JSON.stringify({ ...draft, savedAt: new Date().toISOString() }));
  } catch {
    // No storage: the edit still lives in the editor.
  }
}

export function clearDraft(id: string): void {
  try {
    localStorage.removeItem(id);
  } catch {
    // Nothing to clear.
  }
}
