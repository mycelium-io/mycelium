// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Which open tab reads a notification aloud. Every tab hears every
// notification on its own connection, so they agree on one through a Web Lock
// per message. Only a tab you can see may take it: a hidden one never speaks
// (the system notification covers that). A focused tab takes it at once; a
// visible window without focus, like the app beside your terminal, waits a
// moment so a focused tab gets it first. This is not the tab that rings the
// bell, which is whichever took the ring lock first and may be hidden.

/** How long a visible but unfocused tab waits before taking a message. */
export const UNFOCUSED_DELAY_MS = 300;

/** How long a tab keeps a message's lock, so a tab that hears it late can't
 *  read it again. */
export const CLAIM_HOLD_MS = 10 * 60_000;

export interface TabEnv {
  visible(): boolean;
  focused(): boolean;
  locks: Pick<LockManager, "request"> | null;
  sleep(ms: number): Promise<void>;
}

export const browserTab: TabEnv = {
  visible: () => typeof document !== "undefined" && document.visibilityState === "visible",
  focused: () => typeof document !== "undefined" && document.hasFocus(),
  locks: typeof navigator !== "undefined" && "locks" in navigator ? navigator.locks : null,
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
};

/** Whether this tab should read message `id` aloud. */
export async function claimToSpeak(id: string, env: TabEnv = browserTab): Promise<boolean> {
  if (!env.visible()) return false;
  if (!env.focused()) {
    await env.sleep(UNFOCUSED_DELAY_MS);
    if (!env.visible()) return false;
  }
  // Without Web Locks, tabs can't agree, so only the focused one speaks.
  if (!env.locks) return env.focused();
  return new Promise<boolean>((resolve) => {
    env.locks!
      .request(`mycelium-read-aloud:${id}`, { ifAvailable: true }, async (lock) => {
        resolve(lock !== null);
        if (lock) await env.sleep(CLAIM_HOLD_MS);
      })
      .catch(() => resolve(false));
  });
}
