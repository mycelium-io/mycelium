// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** URL helpers for full-page memory routes and the room link graph.
 *
 * Keys may contain slashes (`decisions/db`). Each path segment is encoded separately
 * so the catch-all route `[...key]` round-trips cleanly. */

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

/** Where the room's full-page memory graph lives: `/room/{room}/graph`. */
export function memoryGraphHref(roomName: string): string {
  return `/room/${encodeURIComponent(roomName)}/graph`;
}
