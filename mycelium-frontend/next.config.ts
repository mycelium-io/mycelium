// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { NextConfig } from "next";

/**
 * Resolve the backend URL with the same precedence the rest of the project uses:
 *   1. NEXT_PUBLIC_API_URL  (.env.local override / CI / prod)
 *   2. server.api_url from ~/.mycelium/config.toml  (matches the CLI + adapters)
 *   3. http://localhost:8000  (mycelium install default)
 *
 * Config-toml read is best-effort and only happens at `next dev` / `next build`
 * — failures fall through silently to the default.
 */
function resolveApiUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  try {
    const path = join(homedir(), ".mycelium", "config.toml");
    const text = readFileSync(path, "utf8");
    // Match `api_url = "..."` under any section. Prefer [server].api_url if present.
    const serverMatch = text.match(/\[server\][\s\S]*?\n\s*api_url\s*=\s*"([^"]+)"/);
    if (serverMatch) return serverMatch[1];
    const anyMatch = text.match(/^\s*api_url\s*=\s*"([^"]+)"/m);
    if (anyMatch) return anyMatch[1];
  } catch {
    /* no config — fall through */
  }
  return "http://localhost:8000";
}

const apiUrl = resolveApiUrl();
// eslint-disable-next-line no-console
console.log(`[mycelium-frontend] backend → ${apiUrl}`);

const nextConfig: NextConfig = {
  // Standalone output → minimal Docker image (no full node_modules in runtime layer)
  output: "standalone",
  env: {
    NEXT_PUBLIC_API_URL: apiUrl,
  },
};

export default nextConfig;
