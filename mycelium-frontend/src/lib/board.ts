// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Display helpers for the coordination board (issue #493). The board is a live
// projection the backend owns (fastapi-backend/app/services/board.py); this
// module just holds the lens grouping the UI renders by, over the API's
// BoardItem shape. When we optimistically mutate a row we recompute counts here
// rather than round-trip, so the two must agree with the server's lens rule.

import type { BoardItem } from "@/lib/api";

/** Where a row lives. The lens (not the raw state) is what the board groups by. */
export type Lens = "needs" | "flight" | "resolved";

/** Which lens a row belongs under — mirrors ``board._lens`` on the backend. */
export function lensOf(item: BoardItem): Lens {
  if (item.state === "resolved") return "resolved";
  if (item.needs_you) return "needs";
  return "flight";
}

/** The header summary: N need you · M in flight · K resolved. */
export function boardCounts(items: BoardItem[]): Record<Lens, number> {
  const counts: Record<Lens, number> = { needs: 0, flight: 0, resolved: 0 };
  for (const it of items) counts[lensOf(it)] += 1;
  return counts;
}
