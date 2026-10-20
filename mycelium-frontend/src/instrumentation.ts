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
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  if (process.env.MYCELIUM_UI_TOKEN_STDIN !== "1" || process.env.MYCELIUM_UI_TOKEN) return;
  const { readFileSync } = await import("node:fs");
  try {
    const token = readFileSync(0, "utf8").trim();
    if (token) process.env.MYCELIUM_UI_TOKEN = token;
  } catch {
    // No token came: every /api request is refused, which says something's wrong.
    process.env.MYCELIUM_UI_TOKEN = "unset";
  }
}
