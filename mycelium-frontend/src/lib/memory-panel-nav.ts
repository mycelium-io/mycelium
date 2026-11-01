// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** Expand ancestor folders in the tree so `key` is visible. */
export function expandedPathsForKey(key: string): string[] {
  const parts = key.split("/");
  const paths: string[] = [];
  for (let i = 1; i < parts.length; i++) {
    paths.push(parts.slice(0, i).join("/"));
  }
  return paths;
}
