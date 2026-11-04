// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The titles of this machine's earlier agent sessions, read by the desktop
 * app (`agent_sessions`, which runs `mycelium machine sessions --json`). A
 * title is the session's own words, so it never goes through the hub: the
 * runner's scan carries only ids, folders and dates. Off the desktop app, or
 * for another machine's sessions, there are none.
 */

import useSWR from "swr";
import { appInvoke } from "@/lib/desktop";

/** One session as the app lists it. */
interface LocalSession {
  framework: string;
  id: string;
  title?: string | null;
}

/** The key a session's title is found by. */
export const titleKey = (framework: string, id: string) => `${framework}:${id}`;

const NONE: ReadonlyMap<string, string> = new Map();

/** This machine's session titles by `titleKey`, while `ask` is set. Empty until the app answers, or if it can't. */
export function useSessionTitles(ask: boolean): ReadonlyMap<string, string> {
  const invoke = appInvoke();
  const { data } = useSWR(
    ask && invoke ? "agent-sessions" : null,
    async () => {
      const got = (await appInvoke()!("agent_sessions")) as LocalSession[] | null;
      const titles = new Map<string, string>();
      for (const s of Array.isArray(got) ? got : []) {
        const title = typeof s?.title === "string" ? s.title.trim() : "";
        if (title && typeof s.framework === "string" && typeof s.id === "string") titles.set(titleKey(s.framework, s.id), title);
      }
      return titles;
    },
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return data ?? NONE;
}
