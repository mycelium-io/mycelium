// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Client-only hooks that read the browser once. Each returns a server snapshot
 * matching the SSR render and a client snapshot reflecting the real browser,
 * so there is no hydration mismatch and no extra render pass.
 */

import { useSyncExternalStore } from "react";
import { isMacPlatform } from "@/lib/keymap";

/** No-op subscribe: these values never change after mount. */
const noSubscribe = () => () => {};

/** True on the client, false during SSR and the hydration snapshot. */
export function useIsClient(): boolean {
  return useSyncExternalStore(noSubscribe, () => true, () => false);
}

/** True on a Mac (⌘ key platform); false in the server snapshot, so ⌘ labels never hydrate on non-Mac. */
export function useIsMac(): boolean {
  return useSyncExternalStore(noSubscribe, () => isMacPlatform(), () => false);
}
