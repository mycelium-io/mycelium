// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Say something went wrong where someone can read it later: the UI server's
 * own output, which the desktop app writes to its log (`desktop.log`). The
 * released app has no console to read a page's errors from.
 *
 * Best effort, and the same line is sent at most once a minute, so a handler
 * failing on every frame can't flood the log.
 */

const QUIET_MS = 60_000;
const MAX_CHARS = 4_000;
const lastSent = new Map<string, number>();

export function reportToApp(line: string): void {
  if (typeof window === "undefined") return;
  const key = line.slice(0, 200);
  const now = Date.now();
  if (now - (lastSent.get(key) ?? -Infinity) < QUIET_MS) return;
  lastSent.set(key, now);
  try {
    void fetch("/api/client-log", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ line: line.slice(0, MAX_CHARS) }),
    }).catch(() => {});
  } catch {
    // Nowhere to send it; the console already has it.
  }
}

/** Forget what was sent. For tests. */
export function resetReports(): void {
  lastSent.clear();
}
