// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Whether a composer's mic is open, in this tab or any other. Reading a
// notification aloud waits while one is: the speakers would play into the
// mic, and the hub would write the notification into the draft.
//
// An open mic holds a shared Web Lock, which the browser releases when its tab
// closes, so a tab that crashes never leaves the others waiting. Opening and
// closing are also announced on a BroadcastChannel, so a tab that's reading
// stops at once rather than at its next check.

const LOCK = "mycelium-mic-open";
const CHANNEL = "mycelium-mic";

let local = 0;
const listeners = new Set<() => void>();
let channel: BroadcastChannel | null = null;

function locks(): LockManager | null {
  return typeof navigator !== "undefined" && "locks" in navigator ? navigator.locks : null;
}

function notify(): void {
  for (const listener of [...listeners]) listener();
}

function bus(): BroadcastChannel | null {
  if (channel || typeof window === "undefined" || typeof window.BroadcastChannel === "undefined") return channel;
  channel = new BroadcastChannel(CHANNEL);
  channel.onmessage = () => notify();
  return channel;
}

function announce(): void {
  notify();
  try {
    bus()?.postMessage("changed");
  } catch {
    // A closed channel only means no other tab hears it now.
  }
}

/** Mark a mic open until the returned function is called. */
export function holdMic(): () => void {
  local++;
  let released = false;
  let release: (() => void) | null = null;
  void locks()
    ?.request(LOCK, { mode: "shared" }, () =>
      released ? undefined : new Promise<void>((resolve) => (release = resolve)),
    )
    .catch(() => {});
  announce();
  return () => {
    if (released) return;
    released = true;
    local--;
    release?.();
    announce();
  };
}

/** Whether a mic is open in this tab or another. */
export async function micOpen(): Promise<boolean> {
  if (local > 0) return true;
  const lm = locks();
  if (!lm?.query) return false;
  try {
    const { held = [] } = await lm.query();
    return held.some((lock) => lock.name === LOCK);
  } catch {
    return false;
  }
}

/** Call `listener` whenever a mic opens or closes, here or in another tab. */
export function onMicChange(listener: () => void): () => void {
  bus();
  listeners.add(listener);
  return () => listeners.delete(listener);
}
