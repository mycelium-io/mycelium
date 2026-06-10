// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { NextConfig } from "next";

/**
 * Internal backend URL used by the Next.js server to proxy `/api/*` requests.
 *
 * The browser never sees this URL — it only talks to its own origin. The
 * Next.js Node process is the one that reaches the backend, so this is a
 * server-side concern resolved at startup with the following precedence:
 *
 *   1. MYCELIUM_INTERNAL_API_URL (preferred — set by compose / runtime env)
 *   2. server.api_url from ~/.mycelium/config.toml (matches the CLI)
 *   3. http://localhost:8000 (mycelium install default)
 *
 * Config-toml read is best-effort — failures fall through to the default.
 */
function resolveInternalApiUrl(): string {
  if (process.env.MYCELIUM_INTERNAL_API_URL) return process.env.MYCELIUM_INTERNAL_API_URL;
  try {
    const path = join(homedir(), ".mycelium", "config.toml");
    const text = readFileSync(path, "utf8");
    const serverMatch = text.match(/\[server\][\s\S]*?\n\s*api_url\s*=\s*"([^"]+)"/);
    if (serverMatch) return serverMatch[1];
    const anyMatch = text.match(/^\s*api_url\s*=\s*"([^"]+)"/m);
    if (anyMatch) return anyMatch[1];
  } catch {
    /* no config — fall through */
  }
  return "http://localhost:8000";
}

const internalApiUrl = resolveInternalApiUrl();
// eslint-disable-next-line no-console
console.log(`[mycelium-frontend] proxy /api/* → ${internalApiUrl}`);

// `next dev` blocks cross-origin requests by default; opt-in via env when
// running dev mode behind a public IP. The Docker production path doesn't
// need this — the browser only ever hits its own origin.
const allowedDevOrigins =
  process.env.MYCELIUM_ALLOWED_DEV_ORIGINS?.split(",")
    .map((s) => s.trim())
    .filter(Boolean) ?? [];

const nextConfig: NextConfig = {
  // Standalone output → minimal Docker image (no full node_modules in runtime layer)
  output: "standalone",
  // Next.js's built-in gzip middleware buffers chunks before flushing, which
  // breaks SSE — events are held until the compressor decides to flush rather
  // than delivered immediately. Disabling compression lets each SSE chunk go
  // straight to the socket. Static assets remain unaffected (served by CDN /
  // reverse proxy in production anyway).
  compress: false,
  allowedDevOrigins,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${internalApiUrl}/api/:path*` },
    ];
  },
};

export default nextConfig;
