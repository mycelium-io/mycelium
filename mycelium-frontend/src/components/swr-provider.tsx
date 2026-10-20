// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { SWRConfig } from "swr";
import { installUiToken } from "@/lib/ui-token";

// Before any request goes out: in the desktop app every `fetch` to this
// server's `/api` carries the launch's token (`lib/ui-token.ts`).
installUiToken();

/**
 * App-wide defaults for the room data hooks (`@/lib/room-data`).
 *
 * The cache is SWR's default one, which lives above the router: navigating
 * between rooms re-mounts every panel but keeps what was already fetched, so a
 * room you have opened before paints from cache and revalidates behind the
 * paint instead of flashing empty.
 *
 * Per-resource polling is set by the hooks themselves; these are the cross-
 * cutting choices. `focusThrottleInterval` is the one worth naming: refocusing
 * the tab should refresh a stale room, but tabbing back and forth shouldn't
 * replay every read in the tree.
 */
export function SWRProvider({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig
      value={{
        revalidateOnFocus: true,
        revalidateOnReconnect: true,
        focusThrottleInterval: 30_000,
        errorRetryCount: 3,
      }}
    >
      {children}
    </SWRConfig>
  );
}
