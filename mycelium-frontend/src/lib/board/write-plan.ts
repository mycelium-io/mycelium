// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Deciding a field write before anything is put on screen.
 *
 * Sits above both `custody` and `fields` because it needs each: where a write
 * may land, and which keys a lease owns.
 *
 * Returning the decision rather than performing it is what keeps the optimistic
 * state honest. A caller has nothing to show until this has answered, so it
 * cannot display a guess for a write that is then refused — which is exactly
 * what the board used to do: show the new value, check whether the write was
 * allowed, print the reason underneath, and leave the row moved anyway.
 */

import { reservedIn } from "./custody";
import { fieldWriteRefusal, memoryKeyOf } from "./fields";
import type { LiveItem } from "./item";

export type FieldWritePlan =
  /** The room will not take this, and this is what to tell whoever tried. */
  | { refused: string }
  /** The memory to write, and the frontmatter to put on it. */
  | { key: string; writable: Record<string, unknown> };

/** What a field write would do, or `null` when there is nothing to write. */
export function planFieldWrite(
  item: LiveItem,
  fields: Record<string, unknown>,
): FieldWritePlan | null {
  const refusal = fieldWriteRefusal(item);
  if (refusal) return { refused: refusal };
  const key = memoryKeyOf(item);
  if (!key) return null;

  // `updated` is the board's name for the store's own `updated_at`, so sending
  // it would write a second, competing timestamp.
  const rest = Object.entries(fields).filter(([name]) => name !== "updated");
  const reserved = reservedIn(rest.map(([name]) => name));
  if (reserved.length) {
    return { refused: `${reserved.join(", ")} moves through a lease, not a field write` };
  }
  // Clearing a field is `null` on the wire: `undefined` would be dropped by
  // JSON.stringify and the key would silently survive.
  const writable = Object.fromEntries(rest.map(([n, v]) => [n, v === undefined ? null : v]));
  return Object.keys(writable).length ? { key, writable } : null;
}
