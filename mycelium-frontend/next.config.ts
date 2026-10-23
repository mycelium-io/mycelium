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
  // No image optimizer. It writes what it makes into `.next/cache/images`
  // beside the server, which in the desktop app is inside the signed app
  // bundle, so the first image it served broke the app's signature. Next has
  // no setting to put that cache elsewhere, and a UI served from this machine
  // has nothing to gain from it: images ship at the size they're shown.
  images: { unoptimized: true },
  // The same for rendered pages: from 16.4, Next writes each page it renders
  // to `.next/server/route-cache/` beside the server, inside the signed app.
  // Kept in memory instead, where it serves just as well for one person's UI.
  experimental: { isrFlushToDisk: false },
  allowedDevOrigins,
  // The desktop app's supervisor, run from a checkout, starts its own `next
  // dev` here, so it runs beside a `pnpm dev` in the same folder (Next allows
  // one dev server per build folder).
  ...(process.env.MYCELIUM_UI_DIST_DIR ? { distDir: process.env.MYCELIUM_UI_DIST_DIR } : {}),
};

export default nextConfig;
