// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { NextConfig } from "next";

// `/api/*` is proxied to the backend by a runtime route handler
// (src/app/api/[...path]/route.ts), NOT a next.config rewrite. Rewrites are
// resolved at *build* time and frozen into the image, so a rewrite destination
// ignored the runtime MYCELIUM_INTERNAL_API_URL and always pointed at the
// build-time default (localhost:8000) — which broke the Dockerized UI. The
// route handler resolves the backend per-request instead. See src/lib/backend.ts.

// `next dev` blocks cross-origin requests by default; opt-in via env when
// running dev mode behind a public IP. The Docker production path doesn't
// need this — the browser only ever hits its own origin.
const allowedDevOrigins =
  process.env.MYCELIUM_ALLOWED_DEV_ORIGINS?.split(",")
    .map((s) => s.trim())
    .filter(Boolean) ?? [];

const nextConfig: NextConfig = {
  // `next dev` sniffs the environment for an AI coding agent (CLAUDECODE,
  // CURSOR_TRACE_ID, …) and, on a match, writes a managed AGENTS.md + CLAUDE.md
  // into the project root unprompted. We don't want the dev server mutating the
  // working tree, so opt out.
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
