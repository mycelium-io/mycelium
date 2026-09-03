// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The floor, read for the roster: which member has a turn open where.
 *
 * A floor is held per thread by a run of backend code (a protocol) and given to
 * the members a step addresses; the hub lists them beside the room's presence.
 * The rail wants the same answer by handle, so this folds the list the other way.
 */

import type { RoomFloor } from "./api";

/** handle (lowercased) → the floor it holds or was given, for badging a row. */
export function floorsByHandle(floors: RoomFloor[]): Map<string, RoomFloor> {
  const out = new Map<string, RoomFloor>();
  for (const floor of floors) {
    out.set(floor.holder.toLowerCase(), floor);
    for (const handle of floor.speakers) out.set(handle.toLowerCase(), floor);
  }
  return out;
}

/** What the row says: the holder holds the floor, a speaker has it. */
export function floorLabel(handle: string, floor: RoomFloor): string {
  const who = handle.toLowerCase();
  const verb = floor.speakers.some((h) => h.toLowerCase() === who) ? "has the floor" : "holds the floor";
  return `${verb} · ${floor.thread}`;
}
