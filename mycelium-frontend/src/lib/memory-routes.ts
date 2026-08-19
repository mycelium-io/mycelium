// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** URL helpers for the full-page memory view (#614).
 *
 * Keys may contain slashes (`decisions/db`). We encode each path segment separately
 * so the catch-all route `[...key]` round-trips cleanly — same contract as the
 * backend memory API path. */

/** Encode a memory key for use in a URL path (one segment per slash). */
export function encodeMemoryKeyPath(key: string): string {
  return key.split("/").map(encodeURIComponent).join("/");
}

/** Decode a catch-all `[...key]` param back to a memory key. */
export function parseMemoryKeyParam(segments: string[]): string {
  return segments.map(decodeURIComponent).join("/");
}

/** Canonical in-app URL for a room memory page. */
export function memoryHref(room: string, key: string): string {
  return `/room/${encodeURIComponent(room)}/memory/${encodeMemoryKeyPath(key)}`;
}
