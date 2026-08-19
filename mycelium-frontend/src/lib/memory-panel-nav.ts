// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { Memory } from "@/lib/api";
import { memoryHref } from "@/lib/memory-routes";

export type MemoryPeekNavigation =
  | { action: "drawer"; memory: Memory }
  | { action: "full-page"; href: string };

/** Rail/chat navigation: peek in the drawer when the memory exists on the hub;
 *  otherwise open the dedicated full-page route (404 UI lives there). */
export async function resolveMemoryPeekNavigation(
  roomName: string,
  key: string,
  memories: Memory[],
  fetchByKey: (room: string, key: string) => Promise<Memory | null>,
): Promise<MemoryPeekNavigation> {
  const cached = memories.find(m => m.key === key);
  if (cached) return { action: "drawer", memory: cached };
  const fetched = await fetchByKey(roomName, key);
  if (fetched) return { action: "drawer", memory: fetched };
  return { action: "full-page", href: memoryHref(roomName, key) };
}

/** Expand ancestor folders in the tree so `key` is visible. */
export function expandedPathsForKey(key: string): string[] {
  const parts = key.split("/");
  const paths: string[] = [];
  for (let i = 1; i < parts.length; i++) {
    paths.push(parts.slice(0, i).join("/"));
  }
  return paths;
}
