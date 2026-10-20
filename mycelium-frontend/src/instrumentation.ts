// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Runs once when the UI server starts, before it answers anything.
 *
 * In the desktop app the supervisor hands this server the launch's token on
 * its stdin (`MYCELIUM_UI_TOKEN_STDIN=1` says it will), never in its
 * environment, which any program running as this user can read. It's kept in
 * this process's own memory from here, where `lib/ui-guard.ts` reads it;
 * setting `process.env` at runtime doesn't change the environment the system
 * shows for the process.
 *
 * If no token arrives (an empty stdin, a failed read), nothing is set, and
 * `lib/ui-guard.ts` refuses every `/api` request: the flag says a token was
 * promised, so its absence is a failure, never a reason to skip the check.
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  if (process.env.MYCELIUM_UI_TOKEN_STDIN !== "1" || process.env.MYCELIUM_UI_TOKEN) return;
  const { readFileSync } = await import("node:fs");
  const token = readToken(() => readFileSync(0, "utf8"));
  if (token) process.env.MYCELIUM_UI_TOKEN = token;
}

/** The token from `read`, or `null` for an empty or failed read. */
export function readToken(read: () => string): string | null {
  try {
    const token = read().trim();
    return token || null;
  } catch {
    return null;
  }
}
