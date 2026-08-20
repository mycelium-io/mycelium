// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { MemoryLink, MemoryLinksIntegrity } from "@/lib/api";

/** One-hop neighbors for the full-page "Related" section.
 *
 * Union of outbound targets and backlink sources, deduped, excluding self. */
export function neighborKeys(key: string, outbound: MemoryLink[], backlinks: MemoryLink[]): string[] {
  const neighbors = new Set<string>();
  for (const link of outbound) {
    if (link.target && link.target !== key) neighbors.add(link.target);
  }
  for (const link of backlinks) {
    const source = link.source ?? link.target;
    if (source && source !== key) neighbors.add(source);
  }
  return [...neighbors].sort((a, b) => a.localeCompare(b));
}

/** How `links.py`'s four `_resolve` failures read to a person. Shared so the
 *  detail view and the graph name the same failure the same way. */
export const LINK_ERRORS: Record<string, string> = {
  not_found: "no such memory",
  no_anchor: "no such section",
  not_expandable: "target is not expandable",
  cross_room: "cross-room links are not supported",
};

export function linkErrorLabel(error?: string | null): string {
  if (!error) return "broken";
  return LINK_ERRORS[error] ?? error;
}

/**
 * Whether an unresolved link is a *defect* rather than a limitation.
 *
 * `myc://rooms/other/key` is documented, legitimate syntax that simply doesn't
 * resolve room-locally — counting it alongside a typo would report a room as
 * broken for doing something correct. The other three failures each mean the
 * author wrote something that doesn't exist.
 */
export function isBrokenLinkError(error?: string | null): boolean {
  return error !== "cross_room";
}

export interface MemoryIntegrityNotes {
  brokenOutbound: number;
  /** inbound === 0 AND outbound === 0 — fully isolated, no connections. */
  isOrphan: boolean;
  /** inbound === 0 AND outbound > 0 — entry point, nothing links here yet. */
  isRoot: boolean;
  /** inbound > 0 AND outbound === 0 — dead end, links arrive but go no further. */
  isLeaf: boolean;
}

/** Per-memory slice of a room integrity report for inline banners.
 *
 * Returns null when there is nothing notable to surface — no broken outbound
 * links and the memory is neither orphaned nor a leaf. Roots (inbound === 0
 * with outbound links) are included in the notes but do not trigger a banner
 * on their own, since being an entry point is intentional, not a problem. */
export function integrityNotesForMemory(
  key: string,
  integrity: MemoryLinksIntegrity | null,
): MemoryIntegrityNotes | null {
  if (!integrity) return null;
  const brokenOutbound = integrity.broken.filter(b => b.source === key).length;
  const isOrphan = integrity.orphans.includes(key);
  const isRoot = (integrity.roots ?? []).includes(key);
  const isLeaf = (integrity.leaves ?? []).includes(key);
  if (brokenOutbound === 0 && !isOrphan && !isLeaf) return null;
  return { brokenOutbound, isOrphan, isRoot, isLeaf };
}
