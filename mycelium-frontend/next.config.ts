// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { NextConfig } from "next";

// `/api/*` is proxied to the backend by a runtime route handler
// (src/app/api/[...path]/route.ts), which resolves MYCELIUM_INTERNAL_API_URL
// per-request. A next.config rewrite resolves at build time instead and
// would freeze in the build-time default. See src/lib/backend.ts.

// `next dev` blocks cross-origin requests by default; opt-in via env when
// running dev mode behind a public IP. The Docker production path doesn't
// need this — the browser only ever hits its own origin.
const allowedDevOrigins =
  process.env.MYCELIUM_ALLOWED_DEV_ORIGINS?.split(",")
    .map((s) => s.trim())
    .filter(Boolean) ?? [];

// `agentRules` is a Next 16.3+ config key; typed locally for compatibility
// with the 16.2.x builds our `^16.2.6` range also resolves to, whose
// `NextConfig` type lacks it. Setting an unknown key on an older runtime is a
// harmless no-op.
const nextConfig: NextConfig & { agentRules?: boolean } = {
  // `next dev` sniffs the environment for an AI coding agent (CLAUDECODE,
  // CURSOR_TRACE_ID, …) and, on a match, writes a managed AGENTS.md + CLAUDE.md
  // into the project root unprompted. Opt out to keep the dev server from
  // mutating the working tree.
  agentRules: false,
  // Standalone output → minimal Docker image (no full node_modules in runtime layer)
  output: "standalone",
  // Next.js's built-in gzip middleware buffers chunks before flushing, which
  // breaks SSE — events are held until the compressor decides to flush rather
  // than delivered immediately. Disabling compression lets each SSE chunk go
  // straight to the socket. Static assets remain unaffected (served by CDN /
  // reverse proxy in production anyway).
  compress: false,
  allowedDevOrigins,
};

export default nextConfig;
