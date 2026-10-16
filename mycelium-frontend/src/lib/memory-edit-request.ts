// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * "Open this memory for editing", from somewhere that only opens memories (a
 * right-click in the Memory rail). The view that draws the memory owns its
 * edit mode, so the ask waits here until that view takes it: on mounting, for
 * a tab opened by the same click, or at once, for a tab already open.
 */

const pending = new Set<string>();
const listeners = new Set<(key: string) => void>();

export function requestMemoryEdit(key: string): void {
  pending.add(key);
  for (const listen of listeners) listen(key);
}

/** Whether an edit is waiting for `key`, without consuming it (safe in render). */
export function memoryEditPending(key: string): boolean {
  return pending.has(key);
}

/** Whether an edit was asked for `key`, consuming the ask. */
export function takeMemoryEdit(key: string): boolean {
  return pending.delete(key);
}

/** Hear asks as they come, for a view already showing a memory. */
export function onMemoryEditRequest(listen: (key: string) => void): () => void {
  listeners.add(listen);
  return () => listeners.delete(listen);
}
