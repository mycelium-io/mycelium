// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useSyncExternalStore } from "react";
import useSWR from "swr";

const noSubscribe = () => () => {};

async function joinedHub(): Promise<string | null> {
  try {
    const res = await fetch("/api/ui/hub", { cache: "no-store" });
    const body = (await res.json()) as { url?: unknown };
    return typeof body.url === "string" ? body.url : null;
  } catch {
    return null;
  }
}

/**
 * The address of the hub this UI talks to: what a CLI, an agent or an invite
 * is told to reach it at, and what the title bar names. The page's own origin
 * when the UI is served beside its hub; the hub's own address when the desktop
 * app's UI on this machine talks to a hub elsewhere (client mode).
 * `serverValue` is what to show while rendering on the server.
 */
export function useHubAddress(serverValue = ""): string {
  const origin = useSyncExternalStore(noSubscribe, () => window.location.origin, () => serverValue);
  const { data } = useSWR("ui-hub", joinedHub, { revalidateOnFocus: false, revalidateOnReconnect: false });
  return data ?? origin;
}
