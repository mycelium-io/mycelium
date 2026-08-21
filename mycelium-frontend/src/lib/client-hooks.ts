// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Client-only React hooks that use useSyncExternalStore to provide a
 * server snapshot that matches the SSR render (avoiding hydration mismatches)
 * and a client snapshot that reflects the real browser environment.
 *
 * These replace the useEffect(() => setState(browserValue), []) pattern that
 * react-hooks/set-state-in-effect flags. useSyncExternalStore is the
 * recommended React 18+ primitive for this class of "read once from the
 * browser, never subscribe" state.
 */

import { useSyncExternalStore } from "react";
import { isMacPlatform } from "@/lib/keymap";

/** No-op subscribe function for values that never change after mount. */
const noSubscribe = () => () => {};

/**
 * Returns true on the client, false during SSR and the server hydration
 * snapshot. Replaces: `const [mounted, setMounted] = useState(false);
 * useEffect(() => setMounted(true), []);`
 */
export function useIsClient(): boolean {
  return useSyncExternalStore(noSubscribe, () => true, () => false);
}

/**
 * Returns true when running on a Mac (⌘ key platform), false otherwise.
 * Server snapshot is false to avoid hydrating ⌘ labels on non-Mac servers.
 * Replaces: `const [mac, setMac] = useState(false);
 * useEffect(() => setMac(isMacPlatform()), []);`
 */
export function useIsMac(): boolean {
  return useSyncExternalStore(noSubscribe, () => isMacPlatform(), () => false);
}
