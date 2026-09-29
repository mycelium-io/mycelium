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
