// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { MemoryLink, MemoryLinksIntegrity } from "@/lib/api";

/** One-hop neighbors for the full-page "Related" section (#614).
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

export interface MemoryIntegrityNotes {
  brokenOutbound: number;
  isOrphan: boolean;
}

/** Per-memory slice of a room integrity report for inline banners. */
export function integrityNotesForMemory(
  key: string,
  integrity: MemoryLinksIntegrity | null,
): MemoryIntegrityNotes | null {
  if (!integrity) return null;
  const brokenOutbound = integrity.broken.filter(b => b.source === key).length;
  const isOrphan = integrity.orphans.includes(key);
  if (brokenOutbound === 0 && !isOrphan) return null;
  return { brokenOutbound, isOrphan };
}
