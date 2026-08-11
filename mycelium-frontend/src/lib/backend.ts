// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/**
 * Resolve the internal backend URL: SERVER-SIDE, at REQUEST time.
 *
 * This MUST be evaluated per-request, never baked into the build: one image
 * runs in dev, Docker, and cloud against different backends. (A next.config
 * rewrite froze this at build time and ignored the runtime env, which broke the
 * Dockerized UI; see next.config.ts.) Precedence:
 *
 *   1. MYCELIUM_INTERNAL_API_URL (compose / runtime env)
 *   2. server.api_url from ~/.mycelium/config.toml (matches the CLI)
 *   3. http://localhost:8000 (mycelium install default)
 *
 * Only import this from server code (route handlers); it reads the filesystem.
 */
export function getBackendUrl(): string {
  if (process.env.MYCELIUM_INTERNAL_API_URL) return process.env.MYCELIUM_INTERNAL_API_URL;
  try {
    const text = readFileSync(join(homedir(), ".mycelium", "config.toml"), "utf8");
    const m =
      text.match(/\[server\][\s\S]*?\n\s*api_url\s*=\s*"([^"]+)"/) ??
      text.match(/^\s*api_url\s*=\s*"([^"]+)"/m);
    if (m) return m[1];
  } catch {
    /* no config; fall through */
  }
  return "http://localhost:8000";
}
