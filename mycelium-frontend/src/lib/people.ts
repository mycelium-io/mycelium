// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * People by name: the hub's user records, read once and shared, so anything
 * that shows who said something can show the name they gave themselves.
 *
 * A message carries its sender's handle. The name is looked up when it's
 * drawn, so a rename shows everywhere at once and a handle with no name reads
 * as it always did. The CLI does the same (`mycelium/names.py`).
 */

import { useMemo } from "react";
import useSWR, { useSWRConfig } from "swr";
import { fetchUsers, type User } from "@/lib/api";

export const USERS_KEY = "users";

/** Every person on the hub, from its user records. */
export function useUsers(): { users: User[]; loading: boolean } {
  const { data, isLoading } = useSWR<User[]>(USERS_KEY, fetchUsers, { refreshInterval: 60_000 });
  return { users: data ?? [], loading: isLoading };
}

/** Handle (lowercased, no `@`) → the name that person gave themselves. */
export function useNames(): Map<string, string> {
  const { users } = useUsers();
  return useMemo(
    () =>
      new Map(
        users
          .filter(u => u.display_name?.trim())
          .map(u => [u.handle.toLowerCase(), u.display_name.trim()] as const),
      ),
    [users],
  );
}

/** Re-read the user records, after a name is set or changed here. */
export function useRefreshUsers(): () => void {
  const { mutate } = useSWRConfig();
  return () => void mutate(USERS_KEY);
}

export function nameOf(names: Map<string, string>, handle: string): string | undefined {
  return names.get(handle.trim().replace(/^@/, "").toLowerCase());
}

/**
 * How well someone matches what was typed after `@`, lower is better, or null
 * for no match. Tries the handle and the name: a handle that starts with it,
 * then any word of the name that does, then either containing it, then its
 * letters in order ("jv" finds Julia Valenti). So `@jul` finds Julia whether
 * her handle is `julia` or `julia@example.com`.
 */
export function mentionRank(query: string, handle: string, name?: string): number | null {
  const q = query.trim().toLowerCase().replace(/^@/, "");
  if (!q) return 0;
  const h = handle.toLowerCase();
  const n = (name ?? "").toLowerCase();
  if (h.startsWith(q)) return 0;
  if (n && n.split(/\s+/).some(w => w.startsWith(q))) return 1;
  if (h.includes(q) || n.includes(q)) return 2;
  const inOrder = (s: string) => {
    let i = 0;
    for (const c of s) if (c === q[i]) i += 1;
    return i === q.length;
  };
  if (inOrder(h) || (n && inOrder(n))) return 3;
  return null;
}

/**
 * A handle made from a name: lowercase, letters and digits kept, anything
 * else folded into one dash. "Julia Valenti" → "julia-valenti".
 */
export function handleFromName(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32);
}
